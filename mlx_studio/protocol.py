"""Validated OpenAI text/tool request protocol. Tool execution belongs to the client."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .structured import parse_json, validate_schema


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FunctionCall(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    arguments: str = Field(max_length=32768)

    @model_validator(mode="after")
    def arguments_object(self):
        value = parse_json(self.arguments)
        if not isinstance(value, dict):
            raise ValueError("工具arguments必须是JSON对象字符串")  # noqa: TRY004 - pydantic validation
        return self


class ToolCall(Strict):
    id: str = Field(min_length=1, max_length=128)
    type: Literal["function"] = "function"
    function: FunctionCall


class Message(Strict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=32768)
    tool_calls: list[ToolCall] | None = Field(default=None, min_length=1, max_length=8)
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def valid_message(self):
        if self.role == "assistant":
            if self.content is None and not self.tool_calls:
                raise ValueError("assistant需要content或tool_calls")
        elif self.role == "tool":
            if self.content is None or not self.tool_call_id:
                raise ValueError("tool消息需要content和tool_call_id")
        elif not self.content or not self.content.strip():
            raise ValueError("system/user消息需要非空content")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("只有assistant可包含tool_calls")
        if self.tool_call_id and self.role != "tool":
            raise ValueError("只有tool可包含tool_call_id")
        return self


class FunctionDefinition(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str | None = Field(default=None, max_length=4096)
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})
    strict: bool = True

    @model_validator(mode="after")
    def schema_valid(self):
        validate_schema(self.parameters)
        if self.parameters.get("type") != "object":
            raise ValueError("工具parameters根类型必须是object")
        return self


class ToolDefinition(Strict):
    type: Literal["function"] = "function"
    function: FunctionDefinition


class NamedFunction(Strict):
    name: str


class NamedChoice(Strict):
    type: Literal["function"] = "function"
    function: NamedFunction


class SchemaDefinition(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str | None = Field(default=None, max_length=4096)
    schema_: dict = Field(alias="schema")
    strict: bool = True


class ResponseFormat(Strict):
    type: Literal["text", "json_object", "json_schema"]
    json_schema: SchemaDefinition | None = None

    @model_validator(mode="after")
    def schema_valid(self):
        if self.type == "json_schema":
            if self.json_schema is None:
                raise ValueError("json_schema模式需要json_schema定义")
            validate_schema(self.json_schema.schema_)
        elif self.json_schema is not None:
            raise ValueError("该输出模式不接受json_schema")
        return self


class Chat(Strict):
    model: str
    messages: list[Message] = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)
    max_tokens: int = Field(default=512, ge=1, le=4096)
    stream: bool = False
    tools: list[ToolDefinition] | None = Field(default=None, min_length=1, max_length=32)
    tool_choice: Literal["auto", "none", "required"] | NamedChoice | None = None
    parallel_tool_calls: bool = True
    response_format: ResponseFormat | None = None

    @model_validator(mode="after")
    def request_valid(self):
        names = [t.function.name for t in self.tools or []]
        if len(names) != len(set(names)):
            raise ValueError("工具名称不可重复")
        if self.tool_choice not in (None, "none", "auto") and not names:
            raise ValueError("强制工具选择需要tools")
        if (
            isinstance(self.tool_choice, NamedChoice)
            and self.tool_choice.function.name not in names
        ):
            raise ValueError("指定的工具不在tools中")
        if (
            names
            and self.tool_choice != "none"
            and self.response_format
            and self.response_format.type != "text"
        ):
            raise ValueError("工具调用和JSON输出不能同时启用；可设置tool_choice=none")
        if len(json.dumps([t.model_dump() for t in self.tools or []])) > 65536:
            raise ValueError("工具定义过大")
        pending, seen = set(), set()
        for m in self.messages:
            if m.role == "tool":
                if m.tool_call_id not in pending:
                    raise ValueError("工具结果ID未知或重复")
                pending.remove(m.tool_call_id)
            else:
                if pending:
                    raise ValueError("继续对话前必须回传所有工具调用结果")
                for call in m.tool_calls or []:
                    if call.id in seen:
                        raise ValueError("工具调用ID不可重复")
                    seen.add(call.id)
                    pending.add(call.id)
        if pending:
            raise ValueError("缺少工具调用结果")
        return self


def response_deltas(message):
    """Validated payloads are chunked after generation; tool IDs/indexes remain stable."""
    for i, call in enumerate(message.get("tool_calls", [])):
        yield {
            "tool_calls": [
                {
                    "index": i,
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["function"]["name"], "arguments": ""},
                }
            ]
        }
        args = call["function"]["arguments"]
        for offset in range(0, len(args), 64):
            yield {
                "tool_calls": [{"index": i, "function": {"arguments": args[offset : offset + 64]}}]
            }
    content = message.get("content")
    if content is not None:
        for offset in range(0, len(content), 64):
            yield {"content": content[offset : offset + 64]}
