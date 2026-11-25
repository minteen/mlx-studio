import asyncio
import hmac
import ipaddress
import json
import os
import platform
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, field_validator

from .catalog import Catalog, download_error
from .protocol import Chat, response_deltas
from .runtime import Runtime
from .structured import GenerationError, output_schema


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelID(Strict):
    id: str

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        return Catalog.validate(value)


class ModelChoice(ModelID):
    kind: Literal["chat", "embedding"]


class Kind(Strict):
    kind: Literal["chat", "embedding"]


class Embedding(Strict):
    model: str
    input: str | list[str]
    encoding_format: Literal["float"] = "float"

    @field_validator("input")
    @classmethod
    def valid_input(cls, value):
        texts = [value] if isinstance(value, str) else value
        if not 1 <= len(texts) <= 32 or any(not s.strip() or len(s) > 8192 for s in texts):
            raise ValueError("请输入1–32条非空文本，每条不超过8192字符")
        return value


class Switch(Strict):
    enabled: bool


def error(message, status=400, code="request_error"):
    return JSONResponse({"error": {"message": message, "type": code, "code": code}}, status)


def create_app(data_dir=None, api_key=None, runtime=None):
    root = Path(data_dir or os.getenv("MLX_STUDIO_DATA", ".data"))
    key = api_key if api_key is not None else os.getenv("MLX_STUDIO_API_KEY", "")
    rt = runtime or Runtime()
    catalog = Catalog(root)
    state = {"enabled": True, "requests": 0, "errors": 0, "started": time.time()}
    operations = {}

    async def model_operation(repo, action, function, *args):
        if repo in operations:
            raise ValueError("该模型正在处理中，请等待操作完成")
        operations[repo] = action
        try:
            return await rt.call(function, *args)
        finally:
            operations.pop(repo, None)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(rt.close)
        await asyncio.to_thread(catalog.close)

    app = FastAPI(title="MLX Studio", lifespan=lifespan)
    app.state.runtime = rt
    app.state.catalog = catalog

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        protected = path.startswith(("/api/", "/v1/"))
        hostname = request.url.hostname or ""
        allowed = {"localhost", "testserver"} | set(
            os.getenv("MLX_STUDIO_ALLOWED_HOSTS", "").split(",")
        )
        if hostname not in allowed:
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                return error("不允许的访问主机名", 403)
        # Block cross-origin writes as well as DNS-rebinding browser access.
        origin = request.headers.get("origin")
        if protected and origin and origin != str(request.base_url).rstrip("/"):
            return error("不允许跨来源访问", 403)
        if (
            protected
            and key
            and not hmac.compare_digest(
                request.headers.get("authorization", "").encode(), f"Bearer {key}".encode()
            )
        ):
            return error("请输入正确的服务访问密钥", 401, "authentication_error")
        if path.startswith("/v1/"):
            if not state["enabled"]:
                return error("推理服务已停止，请在控制台开启", 503, "service_stopped")
            if request.method == "POST":
                state["requests"] += 1
        response = await call_next(request)
        if path.startswith("/v1/") and response.status_code >= 400:
            state["errors"] += 1
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(
            "参数无效："
            + "; ".join(
                ".".join(str(p) for p in e["loc"][1:]) + ": " + e["msg"] for e in exc.errors()
            ),
            422,
            "validation_error",
        )

    @app.exception_handler(GenerationError)
    async def generation_error(request, exc):
        return error(str(exc), exc.status, exc.code)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return error(str(exc), 409, "model_state_error")

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        # Detailed provider exceptions can contain paths/tokens; keep public errors bounded.
        return error(
            f"操作失败 ({type(exc).__name__})。请检查模型兼容性、网络和可用内存。",
            500,
            "runtime_error",
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/status")
    async def status():
        return {
            "enabled": state["enabled"],
            "loaded": dict(rt.loaded),
            "requests": state["requests"],
            "errors": state["errors"],
            "uptime": int(time.time() - state["started"]),
            "platform": f"{platform.system()} {platform.machine()}",
            "operations": dict(operations),
        }

    @app.get("/api/models")
    async def models():
        return await asyncio.to_thread(catalog.list)

    @app.get("/api/search")
    async def search(q: str = "", kind: Literal["chat", "embedding"] | None = None):
        return await asyncio.to_thread(catalog.search, q[:200], kind)

    @app.get("/api/models/info")
    async def model_info(id: str):
        Catalog.validate(id)
        try:
            return await asyncio.to_thread(catalog.info, id)
        except Exception as exc:  # noqa: BLE001 - sanitize provider failures.
            code, message = download_error(exc)
            return error(message, 502, code)

    @app.post("/api/models/download", status_code=202)
    async def download(body: ModelChoice):
        if body.id in operations:
            raise ValueError("该模型正在处理中，请稍后重试")
        return catalog.download(body.id, body.kind)

    @app.post("/api/models/cancel", status_code=202)
    async def cancel_download(body: ModelID):
        return catalog.cancel(body.id)

    @app.post("/api/models/delete")
    async def delete_model(body: ModelID):
        # Check loaded state on the same worker as load/unload, after any queued operation.
        def remove():
            return catalog.delete(body.id, rt.loaded.values())

        return await model_operation(body.id, "deleting", remove)

    @app.post("/api/models/load")
    async def load(body: ModelChoice):
        def load_ready():
            path = catalog.ready_path(body.id, body.kind)
            try:
                rt.load(body.id, body.kind, path)
            except Exception as exc:  # noqa: BLE001 - sanitize model loader failures.
                reason = str(exc).lower()
                if isinstance(exc, MemoryError) or "out of memory" in reason:
                    raise GenerationError(
                        "内存不足，请卸载其他模型或选择更小的量化模型", "out_of_memory", 409
                    ) from None
                if "not supported" in reason or "unsupported" in reason:
                    raise GenerationError(
                        "当前运行库不支持此模型架构，请选择兼容模型", "unsupported_model", 400
                    ) from None
                raise GenerationError(
                    "模型加载失败，请检查文件完整性、模型用途和可用内存",
                    "model_load_error",
                    422,
                ) from None

        await model_operation(body.id, "loading", load_ready)
        return {"loaded": dict(rt.loaded)}

    @app.post("/api/models/unload")
    async def unload(body: Kind):
        repo = rt.loaded.get(body.kind)
        if repo:
            await model_operation(repo, "unloading", rt.unload, body.kind)
        return {"loaded": dict(rt.loaded)}

    @app.post("/api/service")
    async def service(body: Switch):
        state["enabled"] = body.enabled
        return {"enabled": state["enabled"]}

    @app.get("/v1/models")
    async def public_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": repo,
                    "object": "model",
                    "created": int(state["started"]),
                    "owned_by": "mlx-community",
                }
                for repo in rt.loaded.values()
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat(body: Chat):
        Catalog.validate(body.model)
        if rt.loaded.get("chat") != body.model:
            raise ValueError("请先加载请求的对话模型")
        ident, created = "chatcmpl-" + uuid.uuid4().hex, int(time.time())
        base = {"id": ident, "created": created, "model": body.model}
        data = body.model_dump(by_alias=True, exclude_none=True)
        if output_schema(data) is not None:
            await rt.call(rt.prepare, data)
        if body.stream:

            async def events():
                try:
                    first = dict(
                        base,
                        object="chat.completion.chunk",
                        choices=[
                            {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                        ],
                    )
                    yield "data: " + json.dumps(first) + "\n\n"
                    finish = "stop"
                    async for chunk in rt.stream(data):
                        if chunk.get("finish_reason"):
                            finish = chunk["finish_reason"]
                        deltas = (
                            response_deltas(chunk["message"])
                            if "message" in chunk
                            else [{"content": chunk["text"]}]
                        )
                        for delta in deltas:
                            event = dict(
                                base,
                                object="chat.completion.chunk",
                                choices=[{"index": 0, "delta": delta, "finish_reason": None}],
                            )
                            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                    event = dict(
                        base,
                        object="chat.completion.chunk",
                        choices=[{"index": 0, "delta": {}, "finish_reason": finish}],
                    )
                    yield "data: " + json.dumps(event) + "\n\n"
                    yield "data: [DONE]\n\n"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - SSE headers are already committed
                    state["errors"] += 1
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "error": {
                                    "message": str(exc)
                                    if isinstance(exc, GenerationError)
                                    else "生成失败，请检查模型与可用内存",
                                    "code": exc.code
                                    if isinstance(exc, GenerationError)
                                    else "runtime_error",
                                    "type": "generation_error",
                                }
                            }
                        )
                        + "\n\n"
                    )
                    yield "data: [DONE]\n\n"

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        text, last = "", {}
        async for chunk in rt.stream(data):
            text += chunk["text"]
            last = chunk
        prompt_tokens, completion_tokens = (
            last.get("prompt_tokens", 0),
            last.get("completion_tokens", 0),
        )
        return dict(
            base,
            object="chat.completion",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", **last.get("message", {"content": text})},
                    "finish_reason": last.get("finish_reason") or "stop",
                }
            ],
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    @app.post("/v1/embeddings")
    async def embeddings(body: Embedding):
        Catalog.validate(body.model)
        texts = [body.input] if isinstance(body.input, str) else body.input
        vectors, tokens = await rt.call(rt.embed, body.model, texts)
        return {
            "object": "list",
            "model": body.model,
            "data": [
                {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
            ],
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
    return app
