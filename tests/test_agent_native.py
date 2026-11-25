"""Opt-in actual Metal decoding using the already-downloaded small chat model."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mlx_studio.app import create_app
from mlx_studio.runtime import Runtime

pytestmark = pytest.mark.skipif(os.getenv("MLX_STUDIO_SMOKE") != "1", reason="native opt-in")
REPO = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Look up current weather.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "enum": ["Paris"]}},
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}


def test_agent_native(tmp_path):
    path = Path(".data/models/Qwen2.5-0.5B-Instruct-4bit").resolve()
    assert path.exists(), "run tests/test_native.py to download the model first"
    rt = Runtime()
    rt.pool.submit(rt.load, REPO, "chat", str(path)).result()
    with TestClient(create_app(tmp_path, api_key="", runtime=rt)) as client:

        def request(**fields):
            r = client.post(
                "/v1/chat/completions",
                json={
                    "model": REPO,
                    "messages": [
                        {
                            "role": "user",
                            "content": "What is the weather in Paris? Use the provided tool.",
                        }
                    ],
                    "temperature": 0,
                    "max_tokens": 256,
                    **fields,
                },
            )
            assert r.status_code == 200, r.text
            return r

        schema = {
            "type": "object",
            "properties": {
                "city": {"enum": ["Paris"]},
                "days": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1,
                    "maxItems": 2,
                },
            },
            "required": ["city", "days"],
            "additionalProperties": False,
        }
        result = request(
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "trip", "schema": schema},
            }
        ).json()
        print("JSON:", result["choices"][0]["message"]["content"])
        value = json.loads(result["choices"][0]["message"]["content"])
        assert value["city"] == "Paris" and 1 <= len(value["days"]) <= 2
        call_result = request(
            tools=[TOOL], tool_choice="required", parallel_tool_calls=False
        ).json()
        print("Tool:", call_result["choices"][0])
        choice = call_result["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        call = choice["message"]["tool_calls"][0]
        assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}
        messages = [
            {"role": "user", "content": "What is the weather in Paris?"},
            choice["message"],
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": "Paris is 17 degrees Celsius and sunny.",
            },
        ]
        follow = request(messages=messages, tools=[TOOL], tool_choice="none").json()
        print("Tool follow-up:", follow["choices"][0]["message"]["content"])
        assert "17" in follow["choices"][0]["message"]["content"]
        auto = request(messages=messages, tools=[TOOL], tool_choice="auto").json()
        auto_choice = auto["choices"][0]
        # auto is a model decision, not a guarantee it will stop calling tools.
        assert auto_choice["finish_reason"] in ("stop", "tool_calls")
        if auto_choice["finish_reason"] == "tool_calls":
            for invocation in auto_choice["message"]["tool_calls"]:
                assert invocation["function"]["name"] == "get_weather"
                assert json.loads(invocation["function"]["arguments"]) == {"city": "Paris"}
        else:
            assert isinstance(auto_choice["message"]["content"], str)
        print("Auto model decision after result:", auto_choice["finish_reason"])
        stream = request(
            tools=[TOOL],
            tool_choice={"type": "function", "function": {"name": "get_weather"}},
            parallel_tool_calls=False,
            stream=True,
        )
        events = [
            json.loads(s[6:])
            for s in stream.text.split("\n\n")
            if s.startswith("data: ") and s != "data: [DONE]"
        ]
        assert not any("error" in e for e in events), events
        args = "".join(
            tc.get("function", {}).get("arguments", "")
            for e in events
            for tc in e["choices"][0]["delta"].get("tool_calls", [])
        )
        assert json.loads(args) == {"city": "Paris"}
        assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"
        obj = request(
            tools=[TOOL], tool_choice="none", response_format={"type": "json_object"}
        ).json()
        assert isinstance(json.loads(obj["choices"][0]["message"]["content"]), dict)
        truncated = client.post(
            "/v1/chat/completions",
            json={
                "model": REPO,
                "messages": [{"role": "user", "content": "Return an object"}],
                "max_tokens": 1,
                "response_format": {"type": "json_object"},
            },
        )
        assert truncated.status_code == 422, truncated.text
        assert truncated.json()["error"]["code"] == "structured_output_incomplete"
