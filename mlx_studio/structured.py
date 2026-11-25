"""Schema validation, constrained MLX decoding and validated tool envelopes."""

import json
import uuid

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


class GenerationError(Exception):
    def __init__(self, message, code="structured_output_error", status=422):
        super().__init__(message)
        self.code, self.status = code, status


def parse_json(text):
    value = json.loads(text)
    # Reject NaN/Infinity and overflowing numeric literals accepted by Python.
    json.dumps(value, allow_nan=False)
    return value


def validate_schema(schema):
    """Reject unsupported keywords rather than silently weakening constraints."""
    if not isinstance(schema, dict) or len(json.dumps(schema, allow_nan=False)) > 16384:
        raise ValueError("Schema必须是对象且不超过16KB")
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "enum",
        "const",
        "anyOf",
        "title",
        "description",
    }
    nodes = 0

    def visit(node, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 8 or nodes > 256 or not isinstance(node, dict):
            raise ValueError("Schema结构过深、过大或不是对象")
        unknown = set(node) - allowed
        if unknown:
            raise ValueError("不支持的Schema关键字: " + ", ".join(sorted(unknown)))
        if "additionalProperties" in node and not isinstance(node["additionalProperties"], bool):
            raise ValueError("additionalProperties仅支持布尔值")
        for child in node.get("properties", {}).values():
            visit(child, depth + 1)
        if "items" in node:
            visit(node["items"], depth + 1)
        for child in node.get("anyOf", []):
            visit(child, depth + 1)

    try:
        Draft202012Validator.check_schema(schema)
        visit(schema)
    except SchemaError as exc:
        raise ValueError("无效JSON Schema: " + exc.message) from None


def obj(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def output_schema(body):
    tools = body.get("tools") or []
    choice = body.get("tool_choice") or "auto"
    if tools and choice != "none":
        if isinstance(choice, dict):
            tools = [t for t in tools if t["function"]["name"] == choice["function"]["name"]]
        variants = [
            obj(
                {"name": {"const": t["function"]["name"]}, "arguments": t["function"]["parameters"]}
            )
            for t in tools
        ]
        calls = obj(
            {
                "tool_calls": {
                    "type": "array",
                    "items": {"anyOf": variants},
                    "minItems": 1,
                    "maxItems": 8 if body.get("parallel_tool_calls", True) else 1,
                }
            }
        )
        return (
            {"anyOf": [obj({"content": {"type": "string"}}), calls]} if choice == "auto" else calls
        )
    fmt = body.get("response_format") or {}
    if fmt.get("type") == "json_object":
        return {"type": "object"}
    if fmt.get("type") == "json_schema":
        return fmt["json_schema"]["schema"]
    return None


def prompt_messages(body, schema):
    """Use a single JSON tool protocol, independent of model-specific tool tags."""
    messages = []
    for m in body["messages"]:
        if m.get("tool_calls"):
            value = {
                "tool_calls": [
                    {
                        "name": c["function"]["name"],
                        "arguments": parse_json(c["function"]["arguments"]),
                        "id": c["id"],
                    }
                    for c in m["tool_calls"]
                ]
            }
            if m.get("content"):
                value["content"] = m["content"]
            messages.append({"role": "assistant", "content": json.dumps(value, ensure_ascii=False)})
        elif m["role"] == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool result for {m['tool_call_id']}:\n{m['content']}\nUse this result to answer the original user question.",
                }
            )
        else:
            messages.append({"role": m["role"], "content": m.get("content") or ""})
    if schema is not None:
        instruction = (
            "Return only a JSON value matching this schema. No markdown or reasoning.\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        if body.get("tools") and body.get("tool_choice") != "none":
            instruction += (
                "\nChoose tools only when needed to fulfill the user request. "
                "After receiving tool results, answer the user if possible. "
                "Available tools:\n" + json.dumps(body["tools"], ensure_ascii=False)
            )
        if messages and messages[0]["role"] == "system":
            messages[0] = dict(messages[0], content=messages[0]["content"] + "\n\n" + instruction)
        else:
            messages.insert(0, {"role": "system", "content": instruction})
    return messages


def finish_output(body, schema, text, finish):
    if finish == "length":
        raise GenerationError(
            "输出达到max_tokens，结构化结果被截断", "structured_output_incomplete"
        )
    try:
        value = parse_json(text)
        Draft202012Validator(schema).validate(value)
    except (ValueError, ValidationError):
        raise GenerationError("模型输出未通过JSON结构验证") from None
    if body.get("tools") and body.get("tool_choice") != "none":
        if "tool_calls" in value:
            calls = [
                {
                    "id": "call_" + uuid.uuid4().hex,
                    "type": "function",
                    "function": {
                        "name": c["name"],
                        "arguments": json.dumps(c["arguments"], ensure_ascii=False),
                    },
                }
                for c in value["tool_calls"]
            ]
            return {"content": None, "tool_calls": calls}, "tool_calls"
        return {"content": value["content"]}, "stop"
    return {"content": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}, "stop"


class StructuredProcessor:
    """State is private to one request and used only on the fixed MLX thread."""

    def __init__(self, tokenizer, schema):
        from llguidance import LLMatcher

        self.matcher = LLMatcher(tokenizer, LLMatcher.grammar_from_json_schema(schema))
        if self.matcher.is_error() or self.matcher.get_grammar_warnings():
            raise GenerationError("约束引擎不支持此Schema", "unsupported_schema", 400)
        self.offset = None
        self.eos_tokens = set(tokenizer.eos_tokens)

    def __call__(self, tokens, logits):
        import numpy as np
        from llguidance.mlx import apply_token_bitmask

        if self.offset is not None:
            for token in tokens[self.offset :].tolist():
                # MLX computes one token ahead, including after EOS. Do not feed
                # that terminal token into an already completed grammar.
                if self.matcher.is_stopped() and token in self.eos_tokens:
                    continue
                if not self.matcher.consume_token(token):
                    raise GenerationError("约束解码状态错误")
        self.offset = len(tokens)
        if self.matcher.is_stopped() and not self.matcher.is_error():
            import mlx.core as mx

            terminal = mx.full(logits.shape, -float("inf"), dtype=logits.dtype)
            for token in self.eos_tokens:
                terminal[..., token] = 0
            return terminal
        mask = np.frombuffer(self.matcher.compute_bitmask(), dtype=np.int32).copy()
        if self.matcher.is_error():
            raise GenerationError("无法继续生成符合约束的内容")
        return apply_token_bitmask(logits, mask)
