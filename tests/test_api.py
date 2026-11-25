import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from mlx_studio.app import create_app
from mlx_studio.catalog import Catalog
from mlx_studio.runtime import Runtime

CHAT = "mlx-community/test-chat"
EMBED = "mlx-community/test-embed"


class FakeRuntime:
    def __init__(self):
        self.loaded = {"chat": CHAT, "embedding": EMBED}

    async def call(self, fn, *args):
        return fn(*args)

    async def stream(self, body):
        for i, text in enumerate(["你", "好"]):
            yield {
                "text": text,
                "prompt_tokens": 3,
                "completion_tokens": i + 1,
                "finish_reason": "stop" if i else None,
            }

    def load(self, repo, kind, path):
        self.loaded[kind] = repo

    def unload(self, kind):
        self.loaded.pop(kind, None)

    def embed(self, repo, texts):
        if self.loaded.get("embedding") != repo:
            raise ValueError("模型未加载")
        return [[1.0, 0.0] for _ in texts], len(texts) * 2

    def close(self):
        pass


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, api_key="", runtime=FakeRuntime())
    with TestClient(app) as c:
        yield c


def test_chat_protocol_and_usage(client):
    body = {"model": CHAT, "messages": [{"role": "user", "content": "你好"}]}
    result = client.post("/v1/chat/completions", json=body)
    assert result.status_code == 200
    data = result.json()
    assert data["choices"][0]["message"]["content"] == "你好"
    assert data["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    result = client.post("/v1/chat/completions", json={**body, "stream": True})
    assert result.headers["content-type"].startswith("text/event-stream")
    assert "chat.completion.chunk" in result.text and result.text.endswith("data: [DONE]\n\n")
    assert '"finish_reason": "stop"' in result.text


def test_embedding_order_and_validation(client):
    r = client.post("/v1/embeddings", json={"model": EMBED, "input": ["a", "b"]})
    assert r.status_code == 200
    assert [x["index"] for x in r.json()["data"]] == [0, 1]
    for invalid in ["", [], [" "], ["x"] * 33, "x" * 8193]:
        assert (
            client.post("/v1/embeddings", json={"model": EMBED, "input": invalid}).status_code
            == 422
        )
    assert client.post("/v1/embeddings", json={"model": CHAT, "input": "a"}).status_code == 409


def test_service_gate_and_model_lifecycle(client):
    assert len(client.get("/v1/models").json()["data"]) == 2
    assert client.post("/api/service", json={"enabled": False}).json()["enabled"] is False
    assert client.get("/v1/models").status_code == 503
    assert client.get("/api/status").status_code == 200
    client.post("/api/service", json={"enabled": True})
    client.post("/api/models/unload", json={"kind": "chat"})
    assert len(client.get("/v1/models").json()["data"]) == 1
    assert (
        client.post(
            "/v1/chat/completions",
            json={"model": CHAT, "messages": [{"role": "user", "content": "x"}]},
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "repo", ["other/model", "mlx-community/../x", "mlx-community/x/y", "/tmp/x"]
)
def test_reject_external_and_path_models(client, repo):
    assert client.post("/api/models/download", json={"id": repo, "kind": "chat"}).status_code == 422


def test_auth_and_origin_protection(tmp_path):
    with TestClient(create_app(tmp_path, api_key="secret", runtime=FakeRuntime())) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/api/status").status_code == 401
        assert c.post("/api/service", json={"enabled": False}).status_code == 401
        h = {"Authorization": "Bearer secret"}
        assert c.get("/api/status", headers=h).status_code == 200
        assert (
            c.post(
                "/api/service",
                json={"enabled": False},
                headers={**h, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert "secret" not in c.get("/api/status", headers=h).text


def test_invalid_chat_parameters(client):
    body = {"model": CHAT, "messages": [{"role": "user", "content": "x"}]}
    for change in [{"max_tokens": 0}, {"temperature": 3}, {"messages": []}, {"top_p": 0}]:
        r = client.post("/v1/chat/completions", json={**body, **change})
        assert r.status_code == 422 and "error" in r.json()


def test_catalog_persistence_and_interrupted_download(tmp_path, monkeypatch):
    def snapshot(repo, local_dir):
        local_dir.mkdir(parents=True)
        (local_dir / "config.json").write_text("{}")

    monkeypatch.setattr("mlx_studio.catalog.snapshot_download", snapshot)
    catalog = Catalog(tmp_path)
    catalog.download(CHAT, "chat")
    catalog.close()
    restored = Catalog(tmp_path)
    assert restored.list()[0]["status"] == "ready"
    assert restored.list()[0]["bytes"] == 2
    assert restored.ready_path(CHAT, "chat").startswith(str(tmp_path))
    with pytest.raises(ValueError):
        restored.ready_path(CHAT, "embedding")
    restored.models[CHAT]["status"] = "downloading"
    restored._save()
    restored.close()
    interrupted = Catalog(tmp_path)
    assert interrupted.list()[0]["status"] == "error"
    interrupted.close()


def test_runtime_thread_affinity_and_cancellation():
    ids = []

    class Probe(Runtime):
        def _generate(self, body, send, stop):
            ids.append(threading.get_ident())
            for i in range(10000):
                if stop.is_set():
                    return
                send({"text": str(i)})

    rt = Probe()

    async def run():
        thread = await rt.call(threading.get_ident)
        stream = rt.stream({})
        assert (await anext(stream))["text"] == "0"
        await stream.aclose()
        # A following job proves bounded producer has released the worker.
        assert await asyncio.wait_for(rt.call(threading.get_ident), timeout=3) == thread

    try:
        asyncio.run(run())
        assert len(set(ids)) == 1
    finally:
        rt.close()


def test_catalog_lock_prevents_multiple_writers(tmp_path):
    catalog = Catalog(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="数据目录"):
            Catalog(tmp_path)
    finally:
        catalog.close()


def test_search_hub_contract_and_type_filter(client, monkeypatch):
    from types import SimpleNamespace

    from huggingface_hub import HfApi

    def list_models(self, *, author, search, sort, limit):
        assert author == "mlx-community"
        return [
            SimpleNamespace(id=EMBED, pipeline_tag="feature-extraction", downloads=7),
            SimpleNamespace(id=CHAT, pipeline_tag="text-generation", downloads=10),
            SimpleNamespace(id="mlx-community/audio", pipeline_tag="text-to-speech", downloads=1),
        ]

    monkeypatch.setattr(HfApi, "list_models", list_models)
    result = client.get("/api/search?q=test&kind=embedding")
    assert result.status_code == 200
    assert result.json() == [{"id": EMBED, "kind": "embedding", "downloads": 7}]


def test_host_validation(client):
    assert client.get("/api/status", headers={"Host": "attacker.example"}).status_code == 403
