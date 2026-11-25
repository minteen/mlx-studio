"""Validated model catalog and cancellable, isolated snapshot downloads."""

import errno
import fcntl
import json
import multiprocessing
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.errors import HfHubHTTPError

ACTIVE_DOWNLOADS = {"queued", "downloading", "cancelling"}


def download_error(exc):
    """Public errors must not include provider URLs, credentials or local paths."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "disk_full", "磁盘空间不足，请释放空间后重试"
    if isinstance(exc, HfHubHTTPError):
        status = getattr(exc.response, "status_code", None)
        if status in (401, 403):
            return "access_denied", "仓库访问受限，请检查 Hugging Face 授权或模型使用条款"
        if status == 404:
            return "not_found", "模型仓库或版本不存在，请检查模型标识"
    if isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError)):
        return "network_error", "网络连接失败，请检查网络或镜像地址后重试"
    return "download_error", "下载失败，请检查网络、仓库及磁盘空间后重试"


def _snapshot_worker(repo, folder, revision, connection):
    """A process boundary lets cancellation stop HTTP and native Xet transfers."""
    try:
        snapshot_download(repo, local_dir=folder, revision=revision, max_workers=4)
        connection.send(None)
    except Exception as exc:  # noqa: BLE001
        connection.send(download_error(exc))
    finally:
        connection.close()


class DownloadCancelled(Exception):
    pass


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
        self.jobs = {}
        self.futures = {}
        self.metadata = {}
        self.closed = False
        self.models = json.loads(self.file.read_text()) if self.file.exists() else {}
        for item in self.models.values():
            item["speed_bps"] = 0
            if item["status"] in ACTIVE_DOWNLOADS:
                item.update(
                    status="error", error="上次下载被中断，请重试", error_code="interrupted"
                )
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
        folder = self.root / "models" / repo.split("/")[1]
        if folder.is_symlink() or folder.resolve().parent != self.root / "models":
            raise ValueError("模型目录不可使用指向数据目录之外的链接")
        return folder

    @staticmethod
    def folder_size(folder):
        total = 0
        for parent, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
            for name in files:
                path = Path(parent) / name
                if ".cache" in path.relative_to(folder).parts and not name.endswith(".incomplete"):
                    continue
                try:
                    if not path.is_symlink():
                        total += path.stat().st_size
                except FileNotFoundError:  # A download may atomically rename its partial file.
                    pass
        return total

    def _save(self):
        temp = self.file.with_suffix(".tmp")
        temp.write_text(json.dumps(self.models, ensure_ascii=False, indent=2))
        temp.replace(self.file)

    def list(self):
        # Hold the lock so deletion cannot race a listing or overwrite a new status.
        with self.lock:
            items = []
            for entry in self.models.values():
                item = dict(entry)
                item["bytes"] = self.folder_size(self.path(item["id"]))
                total = item.get("total_bytes")
                item["progress"] = (
                    (
                        100
                        if item["status"] == "ready"
                        else min(99, int(item["bytes"] / total * 100))
                    )
                    if total
                    else None
                )
                items.append(item)
            return items

    def info(self, repo, revision=None):
        self.validate(repo)
        cache_key = (repo, revision)
        with self.lock:
            cached = self.metadata.get(cache_key)
            if cached and time.monotonic() - cached[0] < 300:
                return dict(cached[1])
        model = HfApi().model_info(repo, revision=revision, files_metadata=True, timeout=15)
        sizes = [file.size for file in (model.siblings or [])]
        total = sum(sizes) if sizes and all(size is not None for size in sizes) else None
        result = {"id": repo, "total_bytes": total, "revision": model.sha}
        with self.lock:
            self.metadata[cache_key] = (time.monotonic(), result)
        return dict(result)

    def download(self, repo, kind):
        folder = self.path(repo)
        with self.lock:
            if self.closed:
                raise ValueError("服务正在关闭")
            old = self.models.get(repo, {})
            if old and old["kind"] != kind:
                raise ValueError("已有模型的用途不可修改，请先删除后重新下载")
            if old.get("status") in ACTIVE_DOWNLOADS | {"ready"}:
                return dict(old)
            stop = threading.Event()
            item = {
                "id": repo,
                "kind": kind,
                "status": "queued",
                "bytes": self.folder_size(folder),
                "total_bytes": old.get("total_bytes"),
                "revision": old.get("revision"),
                "speed_bps": 0,
                "error": None,
                "error_code": None,
            }
            self.models[repo] = item
            self.jobs[repo] = stop
            self._save()
            self.futures[repo] = self.pool.submit(self._download, repo, stop)
            return dict(item)

    def cancel(self, repo):
        self.validate(repo)
        with self.lock:
            item = self.models.get(repo)
            if not item or item["status"] not in ACTIVE_DOWNLOADS:
                raise ValueError("该模型没有进行中的下载任务")
            self.jobs[repo].set()
            if item["status"] == "queued" and self.futures[repo].cancel():
                item.update(status="cancelled", speed_bps=0)
                self.jobs.pop(repo)
                self.futures.pop(repo)
            else:
                item.update(status="cancelling", speed_bps=0)
            self._save()
            return dict(item)

    def _transfer(self, repo, revision, stop):
        ctx = multiprocessing.get_context("spawn")
        receiver, sender = ctx.Pipe(duplex=False)
        process = ctx.Process(
            target=_snapshot_worker, args=(repo, str(self.path(repo)), revision, sender)
        )
        started = False
        previous = self.folder_size(self.path(repo))
        tick = time.monotonic()
        try:
            if stop.is_set():
                raise DownloadCancelled
            process.start()
            started = True
            sender.close()
            while True:
                if stop.wait(0.25):
                    raise DownloadCancelled
                now = time.monotonic()
                size = self.folder_size(self.path(repo))
                with self.lock:
                    self.models[repo]["speed_bps"] = max(0, int((size - previous) / (now - tick)))
                previous, tick = size, now
                if receiver.poll():
                    try:
                        failure = receiver.recv()
                    except EOFError:
                        raise RuntimeError("下载进程异常结束") from None
                    if failure:
                        return failure
                    return None
                # The child can send its result and exit between poll() and is_alive().
                if not process.is_alive() and not receiver.poll():
                    raise RuntimeError("下载进程异常结束")
        finally:
            if started:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            receiver.close()
            sender.close()

    def _download(self, repo, stop):
        status, message, code = "ready", None, None
        try:
            if stop.is_set():
                raise DownloadCancelled
            with self.lock:
                if stop.is_set():
                    raise DownloadCancelled
                self.models[repo]["status"] = "downloading"
                revision = self.models[repo].get("revision")
            metadata = self.info(repo, revision)
            if stop.is_set():
                raise DownloadCancelled
            with self.lock:
                self.models[repo].update(metadata)
                self._save()
            total = metadata["total_bytes"]
            remaining = max(0, total - self.folder_size(self.path(repo))) if total else 0
            if shutil.disk_usage(self.root).free < remaining + 16 * 1024**2:
                raise OSError(errno.ENOSPC, "Insufficient disk space")
            failure = self._transfer(repo, metadata["revision"], stop)
            if failure:
                code, message = failure
                status = "error"
        except DownloadCancelled:
            status = "cancelled"
        except Exception as exc:  # noqa: BLE001 - sanitize errors before persisting them.
            code, message = download_error(exc)
            status = "error"
        finally:
            with self.lock:
                if stop.is_set():
                    status, message, code = "cancelled", None, None
                self.models[repo].update(status=status, error=message, error_code=code, speed_bps=0)
                self.jobs.pop(repo, None)
                self.futures.pop(repo, None)
                self._save()

    def delete(self, repo, loaded=()):
        folder = self.path(repo)
        with self.lock:
            item = self.models.get(repo)
            if not item:
                raise ValueError("本地模型不存在")
            if repo in loaded:
                raise ValueError("请先将模型卸载出内存，再删除本地文件")
            if item["status"] in ACTIVE_DOWNLOADS:
                raise ValueError("请先取消下载，等待任务停止后再删除")
            size = self.folder_size(folder)
            if folder.exists():
                try:
                    shutil.rmtree(folder)
                except OSError:
                    item.update(
                        status="error",
                        error="删除未完成，请检查文件权限后重试",
                        error_code="delete_failed",
                    )
                    self._save()
                    raise ValueError(item["error"]) from None
            del self.models[repo]
            self._save()
            return {"id": repo, "deleted_bytes": size}

    def ready_path(self, repo, kind):
        folder = self.path(repo)
        with self.lock:
            item = self.models.get(repo)
            if not item or item["status"] != "ready":
                raise ValueError("请先完成模型下载")
            if item["kind"] != kind:
                raise ValueError("模型用途不匹配")
            if not folder.is_dir():
                raise ValueError("模型文件已缺失，请删除清单记录后重新下载")
        return str(folder)

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
        with self.lock:
            self.closed = True
            for event in self.jobs.values():
                event.set()
        self.pool.shutdown(wait=True)
        self.process_lock.close()
