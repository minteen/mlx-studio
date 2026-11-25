"""A minimal agent loop. Run after downloading/loading a chat model.

MLX_STUDIO_MODEL=mlx-community/Qwen2.5-0.5B-Instruct-4bit uv run python examples/agent_tools.py
"""

import json
import os
import urllib.request

URL = os.getenv("MLX_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
MODEL = os.getenv("MLX_STUDIO_MODEL", "mlx-community/Qwen2.5-0.5B-Instruct-4bit")
KEY = os.getenv("MLX_STUDIO_API_KEY", "")
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "city_info",
            "description": "Look up country and time zone of a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "enum": ["Paris", "London", "Shanghai"]}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }
]


def complete(messages, **options):
    request = urllib.request.Request(
        URL + "/chat/completions",
        data=json.dumps(
            {
                "model": MODEL,
                "messages": messages,
                "tools": TOOLS,
                "temperature": 0,
                "max_tokens": 512,
                "parallel_tool_calls": False,
                **options,
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": "Bearer " + KEY} if KEY else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)["choices"][0]["message"]


def main():
    cities = {
        "Paris": {"country": "France", "timezone": "Europe/Paris"},
        "London": {"country": "United Kingdom", "timezone": "Europe/London"},
        "Shanghai": {"country": "China", "timezone": "Asia/Shanghai"},
    }
    messages = [
        {"role": "user", "content": "What country and time zone is Paris in? Use the lookup tool."}
    ]
    # A deterministic two-step demo: call first, then request a final answer.
    for turn in range(4):
        answer = complete(messages, tool_choice="required" if turn == 0 else "none")
        messages.append(answer)
        if not answer.get("tool_calls"):
            print(answer["content"])
            return
        for call in answer["tool_calls"]:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            # Explicit local dispatch: never eval/exec model-produced strings.
            if name != "city_info" or args.get("city") not in cities:
                raise RuntimeError("Unknown tool or invalid arguments")
            result = cities[args["city"]]
            print("Tool:", name, args, "→", result)
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}
            )
    raise RuntimeError("Agent exceeded the maximum of 4 rounds")


if __name__ == "__main__":
    main()
