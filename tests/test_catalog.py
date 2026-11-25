"""Model management regressions; no network or real model weights required."""

import errno
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from mlx_studio.app import create_app
from mlx_studio.catalog import Catalog, DownloadCancelled, download_error
from mlx_studio.runtime import Runtime

REPO = "mlx-community/test-model"
OTHER = "mlx-community/other-model"


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(
        Catalog,
        "info",
        lambda self, repo, revision=None: {
            "id": repo,
            "total_bytes": 8,
            "revision": revision or "fixed-commit",
        },
    )
    instance = Catalog(tmp_path)
    try:
        yield instance
    finally:
        instance.close()


def seed(catalog, repo=REPO, status="ready"):
    folder = catalog.path(repo)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_bytes(b"12345678")
    catalog.models[repo] = {"id": repo, "kind": "chat", "status": status}
    catalog._save()
    return folder


def finish(catalog):
    catalog.pool.submit(lambda: None).result(timeout=5)


def test_sizes_exclude_metadata_and_external_symlinks(catalog, tmp_path):
    folder = seed(catalog)
    cache = folder / ".cache"
    cache.mkdir()
    (cache / "download.metadata").write_bytes(b"x" * 100)
    (cache / "weights.incomplete").write_bytes(b"x" * 4)
    external = tmp_path / "private.txt"
    external.write_bytes(b"x" * 100)
    (folder / "external").symlink_to(external)
    assert catalog.list()[0]["bytes"] == 12
    assert catalog.list()[0]["progress"] is None
    catalog.delete(REPO)
    assert external.stat().st_size == 100


def test_delete_removes_only_selected_model_and_persists(catalog):
    folder = seed(catalog)
    other = seed(catalog, OTHER)
    result = catalog.delete(REPO)
    assert result == {"id": REPO, "deleted_bytes": 8}
    assert not folder.exists() and other.is_dir()
    assert REPO not in catalog.file.read_text()
    assert len(catalog.list()) == 1


@pytest.mark.parametrize("status", ["queued", "downloading", "cancelling"])
def test_delete_rejects_active_download(catalog, status):
    folder = seed(catalog, status=status)
    with pytest.raises(ValueError, match="取消下载"):
        catalog.delete(REPO)
    assert folder.exists()


def test_delete_rejects_loaded_and_missing_models(catalog):
    folder = seed(catalog)
    with pytest.raises(ValueError, match="卸载出内存"):
        catalog.delete(REPO, [REPO])
    assert folder.exists()
    with pytest.raises(ValueError, match="不存在"):
        catalog.delete(OTHER)


def test_delete_rejects_directory_escape(catalog, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("private")
    model_root = catalog.root / "models"
    model_root.mkdir()
    (model_root / "test-model").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="链接"):
        catalog.delete(REPO)
    assert (outside / "keep").read_text() == "private"


def test_delete_failure_keeps_retryable_record(catalog, monkeypatch):
    folder = seed(catalog)

    def fail(path):
        raise PermissionError("/private/path secret-token")

    monkeypatch.setattr("mlx_studio.catalog.shutil.rmtree", fail)
    with pytest.raises(ValueError, match="检查文件权限"):
        catalog.delete(REPO)
    assert folder.exists()
    assert catalog.models[REPO]["error_code"] == "delete_failed"
    assert "secret-token" not in catalog.file.read_text()


def test_cancel_queued_and_running_download_then_resume(catalog, monkeypatch):
    entered = threading.Event()

    def transfer(self, repo, revision, stop):
        folder = self.path(repo)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "weights.incomplete").write_bytes(b"1234")
        entered.set()
        assert stop.wait(3), "cancel signal never arrived"
        raise DownloadCancelled

    monkeypatch.setattr(Catalog, "_transfer", transfer)
    catalog.download(REPO, "chat")
    assert entered.wait(3)
    catalog.download(OTHER, "chat")
    assert catalog.models[OTHER]["status"] == "queued"
    assert catalog.cancel(OTHER)["status"] == "cancelled"
    catalog.delete(OTHER)  # A queued cancellation must not wait for the active transfer.
    catalog.cancel(REPO)
    finish(catalog)
    assert all(item["status"] == "cancelled" for item in catalog.list())
    assert catalog.list()[0]["bytes"] == 4
    assert not catalog.jobs
    with pytest.raises(ValueError, match="没有进行中"):
        catalog.cancel(REPO)

    def resume(self, repo, revision, stop):
        assert revision == "fixed-commit"
        assert (self.path(repo) / "weights.incomplete").read_bytes() == b"1234"
        (self.path(repo) / "weights.incomplete").rename(self.path(repo) / "weights")
        (self.path(repo) / "config.json").write_bytes(b"1234")

    monkeypatch.setattr(Catalog, "_transfer", resume)
    catalog.download(REPO, "chat")
    finish(catalog)
    item = next(m for m in catalog.list() if m["id"] == REPO)
    assert item["status"] == "ready" and item["progress"] == 100
    assert item["bytes"] == 8 and item["speed_bps"] == 0


def test_disk_space_checked_before_transfer(catalog, monkeypatch):
    monkeypatch.setattr(
        "mlx_studio.catalog.shutil.disk_usage", lambda path: SimpleNamespace(free=0)
    )
    catalog.download(REPO, "chat")
    finish(catalog)
    assert catalog.models[REPO]["error_code"] == "disk_full"
    assert catalog.models[REPO]["status"] == "error"


def test_download_failure_is_sanitized_and_can_retry(catalog, monkeypatch):
    def fail(self, repo, revision, stop):
        raise httpx.ConnectError("https://user:secret@example.com /private/path")

    monkeypatch.setattr(Catalog, "_transfer", fail)
    catalog.download(REPO, "chat")
    finish(catalog)
    assert catalog.models[REPO]["error_code"] == "network_error"
    assert "secret" not in catalog.file.read_text()
    monkeypatch.setattr(Catalog, "_transfer", lambda *args: None)
    catalog.download(REPO, "chat")
    finish(catalog)
    assert catalog.models[REPO]["status"] == "ready"


def test_metadata_size_revision_and_cache(tmp_path, monkeypatch):
    calls = []

    def info(self, repo, *, revision, files_metadata, timeout):
        calls.append(repo)
        assert files_metadata and timeout == 15
        return SimpleNamespace(
            sha="revision123",
            siblings=[
                SimpleNamespace(size=20),
                SimpleNamespace(size=30),
            ],
        )

    monkeypatch.setattr("mlx_studio.catalog.HfApi.model_info", info)
    catalog = Catalog(tmp_path)
    try:
        assert catalog.info(REPO)["total_bytes"] == 50
        assert catalog.info(REPO)["revision"] == "revision123"
        assert calls == [REPO]
        monkeypatch.setattr(
            "mlx_studio.catalog.HfApi.model_info",
            lambda *a, **k: SimpleNamespace(
                sha="unknown-size",
                siblings=[SimpleNamespace(size=None)],
            ),
        )
        assert catalog.info(OTHER)["total_bytes"] is None
    finally:
        catalog.close()


def test_shutdown_cancels_download_and_restart_recovers_states(catalog, monkeypatch):
    entered = threading.Event()

    def transfer(self, repo, revision, stop):
        entered.set()
        assert stop.wait(3)
        raise DownloadCancelled

    monkeypatch.setattr(Catalog, "_transfer", transfer)
    catalog.download(REPO, "chat")
    assert entered.wait(3)
    # Use the same stop protocol as shutdown without closing the fixture twice.
    catalog.jobs[REPO].set()
    finish(catalog)
    assert catalog.models[REPO]["status"] == "cancelled"
    for status in ("queued", "downloading", "cancelling"):
        seed(catalog, f"mlx-community/{status}", status)
    # A separate catalog will recover these after the process lock is released.
    root = catalog.root
    catalog.process_lock.close()
    restored = Catalog(root)
    try:
        assert all(m["error_code"] == "interrupted" for m in restored.list() if m["id"] != REPO)
    finally:
        restored.close()


def blocking_worker(repo, folder, revision, connection):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "worker-started").touch()
    while True:
        time.sleep(0.05)


def test_cancel_terminates_actual_worker_process(catalog, monkeypatch):
    monkeypatch.setattr("mlx_studio.catalog._snapshot_worker", blocking_worker)
    stop = threading.Event()
    baseline = {p.pid for p in multiprocessing.active_children()}
    catalog.models[REPO] = {"id": REPO, "kind": "chat", "status": "downloading"}
    errors = []

    def run():
        try:
            catalog._transfer(REPO, "fixed", stop)
        except DownloadCancelled:
            errors.append("cancelled")

    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not (catalog.path(REPO) / "worker-started").exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
    finally:
        stop.set()
        thread.join(timeout=8)
    assert not thread.is_alive()
    assert errors == ["cancelled"]
    assert {p.pid for p in multiprocessing.active_children()} == baseline


class LifecycleRuntime(Runtime):
    def load(self, repo, kind, path):
        if self.failure:
            raise self.failure
        self.loaded[kind] = repo

    def unload(self, kind):
        self.loaded.pop(kind, None)

    failure = None


def test_management_api_auth_deletion_and_loader_errors(tmp_path, monkeypatch):
    runtime = LifecycleRuntime()
    app = create_app(tmp_path, api_key="test-key", runtime=runtime)
    folder = seed(app.state.catalog)
    with TestClient(app) as client:
        body = {"id": REPO}
        for endpoint in ("delete", "cancel"):
            assert client.post(f"/api/models/{endpoint}", json=body).status_code == 401
        assert client.get("/api/models/info", params=body).status_code == 401
        headers = {"Authorization": "Bearer test-key"}
        for failure, code in [
            (MemoryError("secret"), "out_of_memory"),
            (ValueError("unsupported model secret"), "unsupported_model"),
            (RuntimeError("/private/path secret"), "model_load_error"),
        ]:
            runtime.failure = failure
            response = client.post(
                "/api/models/load", headers=headers, json={**body, "kind": "chat"}
            )
            assert response.json()["error"]["code"] == code
            assert "secret" not in response.text
            assert client.get("/api/status", headers=headers).json()["operations"] == {}
        runtime.failure = None
        assert (
            client.post(
                "/api/models/load", headers=headers, json={**body, "kind": "chat"}
            ).status_code
            == 200
        )
        assert client.post("/api/models/delete", headers=headers, json=body).status_code == 409
        assert folder.exists()
        assert (
            client.post("/api/models/unload", headers=headers, json={"kind": "chat"}).status_code
            == 200
        )
        assert (
            client.post("/api/models/delete", headers=headers, json=body).json()["deleted_bytes"]
            == 8
        )
        assert not folder.exists()
        assert client.get("/api/models", headers=headers).json() == []
        assert (
            client.post("/api/models/delete", headers=headers, json={"id": "../x"}).status_code
            == 422
        )


def test_disk_error_redaction():
    assert download_error(OSError(errno.ENOSPC, "secret"))[0] == "disk_full"


def successful_worker(repo, folder, revision, connection):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "config.json").write_text("{}")
    connection.send(None)
    connection.close()


def failed_worker(repo, folder, revision, connection):
    connection.send(("network_error", "网络连接失败，请重试"))
    connection.close()


@pytest.mark.parametrize(
    "worker,expected",
    [
        (successful_worker, None),
        (failed_worker, ("network_error", "网络连接失败，请重试")),
    ],
)
def test_worker_result_transport_and_cleanup(catalog, monkeypatch, worker, expected):
    monkeypatch.setattr("mlx_studio.catalog._snapshot_worker", worker)
    catalog.models[REPO] = {"id": REPO, "kind": "chat", "status": "downloading"}
    baseline = {p.pid for p in multiprocessing.active_children()}
    assert catalog._transfer(REPO, "fixed", threading.Event()) == expected
    assert {p.pid for p in multiprocessing.active_children()} == baseline


def test_inflight_load_blocks_duplicate_load_delete_and_download(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class BlockingRuntime(LifecycleRuntime):
        def load(self, repo, kind, path):
            entered.set()
            assert release.wait(5)
            super().load(repo, kind, path)

    app = create_app(tmp_path, api_key="", runtime=BlockingRuntime())
    seed(app.state.catalog)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as requests:
        body = {"id": REPO, "kind": "chat"}
        task = requests.submit(client.post, "/api/models/load", json=body)
        try:
            assert entered.wait(3)
            assert client.get("/api/status").json()["operations"] == {REPO: "loading"}
            for endpoint, payload in [("load", body), ("download", body), ("delete", {"id": REPO})]:
                response = client.post("/api/models/" + endpoint, json=payload)
                assert response.status_code == 409
        finally:
            release.set()
        assert task.result(timeout=3).status_code == 200
        assert client.get("/api/status").json()["operations"] == {}
        assert app.state.catalog.path(REPO).exists()


def test_model_info_endpoint_reports_sizes_and_sanitizes_failures(tmp_path, monkeypatch):
    app = create_app(tmp_path, api_key="", runtime=LifecycleRuntime())
    monkeypatch.setattr(
        Catalog,
        "info",
        lambda self, repo: {
            "id": repo,
            "total_bytes": 123,
            "revision": "fixed",
        },
    )
    with TestClient(app) as client:
        assert client.get("/api/models/info", params={"id": REPO}).json()["total_bytes"] == 123
        assert client.get("/api/models/info", params={"id": "../private"}).status_code == 409

        def fail(self, repo):
            raise httpx.ConnectError("secret-token /private/path")

        monkeypatch.setattr(Catalog, "info", fail)
        response = client.get("/api/models/info", params={"id": REPO})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "network_error"
        assert "secret-token" not in response.text
