"""All Metal operations stay on one dedicated thread; only Python values cross it."""

import asyncio
import gc
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

from .structured import (
    GenerationError,
    StructuredProcessor,
    finish_output,
    output_schema,
    prompt_messages,
)


class Runtime:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
        self.models = {}
        self.loaded = {}
        self.stops = set()
        self.grammar_tokenizers = {}

    async def call(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self.pool, function, *args)

    def load(self, repo, kind, path):
        if self.loaded.get(kind) == repo:
            return
        # Construct first: a failed load leaves the previous model intact.
        if kind == "chat":
            from mlx_lm import load
        else:
            from mlx_embeddings import load
        model, tokenizer = load(path, tokenizer_config={"trust_remote_code": False})
        if kind == "chat":
            self.grammar_tokenizers.clear()
        self.models[kind] = (model, tokenizer)
        self.loaded[kind] = repo
        gc.collect()
        import mlx.core as mx

        mx.clear_cache()

    def unload(self, kind):
        if kind == "chat":
            self.grammar_tokenizers.clear()
        self.models.pop(kind, None)
        self.loaded.pop(kind, None)
        gc.collect()
        import mlx.core as mx

        mx.clear_cache()

    def check(self, kind, repo):
        if self.loaded.get(kind) != repo:
            raise ValueError("请求模型尚未加载或用途不符，请在模型库加载")
        return self.models[kind]

    def _processor(self, body):
        schema = output_schema(body)
        if schema is None:
            return None
        _, tokenizer = self.check("chat", body["model"])
        if body["model"] not in self.grammar_tokenizers:
            from llguidance.hf import from_tokenizer

            try:
                self.grammar_tokenizers[body["model"]] = from_tokenizer(tokenizer._tokenizer)
            except (ValueError, TypeError, AttributeError):
                raise GenerationError(
                    "该模型分词器不支持约束输出", "unsupported_tokenizer", 400
                ) from None
        return StructuredProcessor(self.grammar_tokenizers[body["model"]], schema)

    def prepare(self, body):
        # Validate compiler/tokenizer support before committing SSE headers.
        self._processor(body)

    def _generate(self, body, send, stop):
        model, tokenizer = self.check("chat", body["model"])
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        schema = output_schema(body)
        processor = self._processor(body)
        prompt = tokenizer.apply_chat_template(
            prompt_messages(body, schema), tokenize=False, add_generation_prompt=True
        )
        iterator = stream_generate(
            model,
            tokenizer,
            prompt,
            max_tokens=body["max_tokens"],
            logits_processors=[processor] if processor else None,
            sampler=make_sampler(temp=body["temperature"], top_p=body["top_p"]),
        )
        text, last = "", None
        try:
            for result in iterator:
                if stop.is_set():
                    return
                last = result
                if schema is not None:
                    text += result.text
                    continue
                send(
                    {
                        "text": result.text,
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.generation_tokens,
                        "finish_reason": result.finish_reason,
                    }
                )
            if schema is not None and not stop.is_set():
                message, finish = finish_output(
                    body, schema, text, last.finish_reason if last else None
                )
                send(
                    {
                        "text": "",
                        "message": message,
                        "finish_reason": finish,
                        "prompt_tokens": last.prompt_tokens if last else 0,
                        "completion_tokens": last.generation_tokens if last else 0,
                    }
                )
        finally:
            iterator.close()

    async def stream(self, body):
        buffer = queue.Queue(maxsize=32)
        stop = threading.Event()
        self.stops.add(stop)

        def send(item):
            while not stop.is_set():
                try:
                    buffer.put(item, timeout=0.1)
                    return
                except queue.Full:
                    pass

        def produce():
            try:
                if not stop.is_set():
                    self._generate(body, send, stop)
            except Exception as exc:  # noqa: BLE001 - pass worker errors to async consumer
                send(exc)
            finally:
                send(None)

        future = self.pool.submit(produce)
        try:
            while True:
                try:
                    item = buffer.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()
            self.stops.discard(stop)
            future.cancel()

    def embed(self, repo, texts):
        model, tokenizer = self.check("embedding", repo)
        import mlx.core as mx
        from mlx_embeddings import generate

        result = generate(model, tokenizer, texts=texts, max_length=512)
        mx.eval(result.text_embeds)
        vectors = result.text_embeds.tolist()
        # Count the same truncated tokenization used by generate.
        tokens = sum(min(len(tokenizer.encode(text)), 512) for text in texts)
        return vectors, tokens

    def close(self):
        for event in list(self.stops):
            event.set()

        def clear():
            self.grammar_tokenizers.clear()
            self.models.clear()
            self.loaded.clear()
            gc.collect()

        self.pool.submit(clear).result()
        self.pool.shutdown(wait=True, cancel_futures=True)
