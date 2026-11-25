"""Validated model catalog and background snapshot downloads."""

import fcntl
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


class Catalog:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.process_lock = (self.root / ".lock").open("a")
        try:
            fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.process_lock.close()
            raise RuntimeError("数据目录已由另一个 MLX Studio 进程使用") from None
        self.file = self.root / "models.json"
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="download")
        self.models = json.loads(self.file.read_text()) if self.file.exists() else {}
        for item in self.models.values():
            if item["status"] == "downloading":
                item.update(status="error", error="上次下载被中断，请重试")
        self._save()

    @staticmethod
    def validate(repo: str):
        if (
            not re.fullmatch(r"mlx-community/[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", repo)
            or ".." in repo
        ):
            raise ValueError("仅支持 mlx-community/ 下的有效模型标识")
        return repo

    def path(self, repo):
        self.validate(repo)
        return self.root / "models" / repo.split("/")[1]

    def _save(self):
        temp = self.file.with_suffix(".tmp")
        temp.write_text(json.dumps(self.models, ensure_ascii=False, indent=2))
        temp.replace(self.file)

    def list(self):
        with self.lock:
            items = [dict(item) for item in self.models.values()]
        for item in items:
            folder = self.path(item["id"])
            item["bytes"] = sum(
                p.stat().st_size
                for p in folder.rglob("*")
                if p.is_file() and (".cache" not in p.parts or p.name.endswith(".incomplete"))
            )
        return items

    def download(self, repo, kind):
        self.validate(repo)
        with self.lock:
            old = self.models.get(repo)
            if old and old["status"] == "downloading":
                return dict(old)
            if old and old["status"] == "ready":
                if old["kind"] != kind:
                    raise ValueError("已下载模型的用途不可修改")
                return dict(old)
            item = {"id": repo, "kind": kind, "status": "downloading", "bytes": 0, "error": None}
            self.models[repo] = item
            self._save()
        self.pool.submit(self._download, repo)
        return dict(item)

    def _download(self, repo):
        try:
            snapshot_download(repo, local_dir=self.path(repo))
            status, error = "ready", None
        except Exception as exc:  # noqa: BLE001 - persist provider failure in background task
            status, error = (
                "error",
                f"下载失败 ({type(exc).__name__})，请检查网络、仓库和可用磁盘后重试",
            )
        with self.lock:
            self.models[repo].update(status=status, error=error)
            self._save()

    def ready_path(self, repo, kind):
        self.validate(repo)
        with self.lock:
            item = self.models.get(repo)
            if not item or item["status"] != "ready":
                raise ValueError("请先完成模型下载")
            if item["kind"] != kind:
                raise ValueError("模型用途不匹配")
        return str(self.path(repo))

    @staticmethod
    def search(query, kind=None):
        results = HfApi().list_models(
            author="mlx-community", search=query, sort="downloads", limit=50
        )
        items = []
        for model in results:
            pipeline = model.pipeline_tag or ""
            if pipeline not in ("", "text-generation", "feature-extraction", "sentence-similarity"):
                continue
            guess = (
                "embedding"
                if pipeline in ("feature-extraction", "sentence-similarity")
                or any(word in model.id.lower() for word in ("embed", "minilm", "bge-", "e5-"))
                else "chat"
            )
            if kind and guess != kind:
                continue
            items.append({"id": model.id, "kind": guess, "downloads": model.downloads or 0})
        return items

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.process_lock.close()
