import json
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_api import CHAT, FakeRuntime

from mlx_studio.app import create_app
from mlx_studio.protocol import Chat
from mlx_studio.structured import GenerationError, finish_output, output_schema, validate_schema

TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
BASE = {"model": CHAT, "messages": [{"role": "user", "content": "Find this"}]}


class StructuredRuntime(FakeRuntime):
    payload: ClassVar[dict] = {
        "tool_calls": [{"name": "lookup", "arguments": {"query": "中文查询" * 40}}]
    }
    failure = None

    def prepare(self, body):
        pass

    async def stream(self, body):
        if self.failure:
            raise self.failure
        schema = output_schema(body)
        if schema is None:
            async for chunk in super().stream(body):
                yield chunk
        else:
            message, finish = finish_output(body, schema, json.dumps(self.payload), "stop")
            yield {
                "text": "",
                "message": message,
                "finish_reason": finish,
                "prompt_tokens": 4,
                "completion_tokens": 10,
            }


@pytest.fixture
def endpoint(tmp_path):
    rt = StructuredRuntime()
    with TestClient(create_app(tmp_path, api_key="", runtime=rt)) as client:
        yield client, rt


def events(text):
    return [
        json.loads(s[6:])
        for s in text.split("\n\n")
        if s.startswith("data: ") and s != "data: [DONE]"
    ]


def test_tool_stream_reassembly_and_roundtrip(endpoint):
    client, rt = endpoint
    body = {**BASE, "tools": [TOOL], "tool_choice": "required", "parallel_tool_calls": False}
    result = client.post("/v1/chat/completions", json=body)
    assert result.status_code == 200, result.text
    choice = result.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls" and choice["message"]["content"] is None
    call = choice["message"]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == rt.payload["tool_calls"][0]["arguments"]
    stream = events(client.post("/v1/chat/completions", json={**body, "stream": True}).text)
    assembled = {}
    for frame in stream:
        for tc in frame["choices"][0]["delta"].get("tool_calls", []):
            old = assembled.setdefault(tc["index"], {"arguments": ""})
            if "id" in tc:
                old["id"] = tc["id"]
            old["arguments"] += tc["function"].get("arguments", "")
    assert assembled[0]["id"].startswith("call_")
    assert json.loads(assembled[0]["arguments"]) == json.loads(call["function"]["arguments"])
    assert stream[-1]["choices"][0]["finish_reason"] == "tool_calls"
    history = BASE["messages"] + [
        choice["message"],
        {"role": "tool", "tool_call_id": call["id"], "content": "Found it"},
    ]
    response = client.post(
        "/v1/chat/completions",
        json={**BASE, "messages": history, "tools": [TOOL], "tool_choice": "none"},
    )
    assert (
        response.status_code == 200
        and response.json()["choices"][0]["message"]["content"] == "你好"
    )


@pytest.mark.parametrize(
    "choice", ["required", {"type": "function", "function": {"name": "lookup"}}]
)
def test_required_and_named_reject_plain_answer(endpoint, choice):
    client, rt = endpoint
    rt.payload = {"content": "I will not call anything"}
    r = client.post("/v1/chat/completions", json={**BASE, "tools": [TOOL], "tool_choice": choice})
    assert r.status_code == 422 and r.json()["error"]["code"] == "structured_output_error"


def test_auto_accepts_plain_answer_and_multiple_calls(endpoint):
    client, rt = endpoint
    rt.payload = {"content": "Done"}
    body = {**BASE, "tools": [TOOL]}
    r = client.post("/v1/chat/completions", json=body)
    assert r.json()["choices"][0]["message"] == {"role": "assistant", "content": "Done"}
    rt.payload = {
        "tool_calls": [
            {"name": "lookup", "arguments": {"query": "one"}},
            {"name": "lookup", "arguments": {"query": "two"}},
        ]
    }
    r = client.post("/v1/chat/completions", json=body)
    calls = r.json()["choices"][0]["message"]["tool_calls"]
    assert len(calls) == 2 and calls[0]["id"] != calls[1]["id"]
    assert (
        client.post("/v1/chat/completions", json={**body, "parallel_tool_calls": False}).status_code
        == 422
    )


def test_json_schema_and_stream(endpoint):
    client, rt = endpoint
    rt.payload = {"status": "ok", "nested": {"ids": [1, 2]}}
    schema = {
        "type": "object",
        "properties": {
            "status": {"enum": ["ok"]},
            "nested": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "integer"}, "minItems": 2}
                },
                "required": ["ids"],
                "additionalProperties": False,
            },
        },
        "required": ["status", "nested"],
        "additionalProperties": False,
    }
    body = {
        **BASE,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": schema},
        },
    }
    r = client.post("/v1/chat/completions", json=body)
    assert r.status_code == 200, r.text
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == rt.payload
    stream = events(client.post("/v1/chat/completions", json={**body, "stream": True}).text)
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in stream)
    assert json.loads(text) == rt.payload
    rt.payload = {"status": "wrong"}
    assert client.post("/v1/chat/completions", json=body).status_code == 422


def test_stream_failure_has_error_and_no_success_finish(endpoint):
    client, rt = endpoint
    rt.failure = GenerationError("truncated", "structured_output_incomplete")
    body = {**BASE, "response_format": {"type": "json_object"}}
    assert client.post("/v1/chat/completions", json=body).status_code == 422
    frames = events(client.post("/v1/chat/completions", json={**body, "stream": True}).text)
    assert frames[-1]["error"]["code"] == "structured_output_incomplete"
    assert not any(e.get("choices", [{}])[0].get("finish_reason") for e in frames)


@pytest.mark.parametrize(
    "change",
    [
        {"tools": [TOOL, TOOL]},
        {"tool_choice": "required"},
        {"tools": [TOOL], "tool_choice": {"type": "function", "function": {"name": "missing"}}},
        {"tools": [TOOL], "response_format": {"type": "json_object"}},
        {"response_format": {"type": "json_schema"}},
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "x", "schema": {"$ref": "https://example.com"}},
            }
        },
        {"messages": [{"role": "tool", "content": "x", "tool_call_id": "unknown"}]},
        {"messages": [{"role": "assistant", "content": None}]},
        {"tools": []},
    ],
)
def test_invalid_requests_rejected_before_inference(endpoint, change):
    client, _ = endpoint
    assert client.post("/v1/chat/completions", json={**BASE, **change}).status_code == 422


@pytest.mark.parametrize(
    "text",
    [
        '{"tool_calls":[{"name":"other","arguments":{"query":"x"}}]}',
        '{"tool_calls":[{"name":"lookup","arguments":{}}]}',
        '{"tool_calls":[{"name":"lookup","arguments":{"query":3}}]}',
    ],
)
def test_invalid_generated_tools_not_delivered(text):
    body = Chat.model_validate({**BASE, "tools": [TOOL]}).model_dump(
        by_alias=True, exclude_none=True
    )
    with pytest.raises(GenerationError):
        finish_output(body, output_schema(body), text, "stop")


def test_history_ids_and_json_arguments():
    def call(id, args="{}"):
        return {"id": id, "type": "function", "function": {"name": "lookup", "arguments": args}}

    assistant = {"role": "assistant", "tool_calls": [call("a")]}
    tool = {"role": "tool", "tool_call_id": "a", "content": ""}
    Chat.model_validate({**BASE, "messages": BASE["messages"] + [assistant, tool]})
    for history in [
        [assistant],
        [assistant, tool, tool],
        [assistant, tool, assistant, tool],
        [{"role": "assistant", "tool_calls": [call("a", "[]")]}],
        [{"role": "assistant", "tool_calls": [call("a", '{"x":NaN}')]}],
    ]:
        with pytest.raises(ValidationError):
            Chat.model_validate({**BASE, "messages": BASE["messages"] + history})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "patternProperties": {}},
        {"type": "number", "minimum": 0},
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"type": "invalid"},
        {"const": float("inf")},
    ],
)
def test_unsupported_schema_is_not_silently_ignored(schema):
    with pytest.raises(ValueError):
        validate_schema(schema)


def test_truncation_and_nonfinite_values():
    for text, finish in [('{"x":1}', "length"), ('{"x":NaN}', "stop"), ('{"x":1e9999}', "stop")]:
        with pytest.raises(GenerationError):
            finish_output({}, {"type": "object"}, text, finish)
