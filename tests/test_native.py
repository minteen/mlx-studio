"""Opt-in integration: downloads small, real mlx-community models."""

import math
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mlx_studio.app import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("MLX_STUDIO_SMOKE") != "1", reason="set MLX_STUDIO_SMOKE=1"
)


def test_native_models():
    root = Path(os.getenv("MLX_STUDIO_DATA", ".data"))
    with TestClient(create_app(root, api_key="")) as client:
        for repo, kind in [
            ("mlx-community/Qwen2.5-0.5B-Instruct-4bit", "chat"),
            ("mlx-community/all-MiniLM-L6-v2-4bit", "embedding"),
        ]:
            r = client.post("/api/models/download", json={"id": repo, "kind": kind})
            assert r.status_code == 202, r.text
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                item = next(m for m in client.get("/api/models").json() if m["id"] == repo)
                if item["status"] != "downloading":
                    break
                time.sleep(1)
            assert item["status"] == "ready", item
            r = client.post("/api/models/load", json={"id": repo, "kind": kind})
            assert r.status_code == 200, r.text
        chat = client.post(
            "/v1/chat/completions",
            json={
                "model": "mlx-community/Qwen2.5-0.5B-Instruct-4bit",
                "messages": [{"role": "user", "content": "Say hello in one word."}],
                "max_tokens": 16,
                "temperature": 0,
            },
        )
        assert chat.status_code == 200, chat.text
        assert chat.json()["choices"][0]["message"]["content"].strip()
        print("Native chat:", chat.json()["choices"][0]["message"]["content"])
        vectors = client.post(
            "/v1/embeddings",
            json={
                "model": "mlx-community/all-MiniLM-L6-v2-4bit",
                "input": [
                    "A cat sits on a mat.",
                    "A kitten rests on a rug.",
                    "Stock prices rose today.",
                ],
            },
        )
        assert vectors.status_code == 200, vectors.text
        data = vectors.json()["data"]
        assert len(data) == 3
        assert all(len(item["embedding"]) == 384 for item in data)
        assert all(math.isfinite(v) for item in data for v in item["embedding"])
        print("Native embeddings:", len(data), "x", len(data[0]["embedding"]))
        stream = client.post(
            "/v1/chat/completions",
            json={
                "model": "mlx-community/Qwen2.5-0.5B-Instruct-4bit",
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 8,
                "stream": True,
            },
        )
        assert "[DONE]" in stream.text and '"error"' not in stream.text, stream.text
        client.post("/api/service", json={"enabled": False})
        assert client.get("/v1/models").status_code == 503
