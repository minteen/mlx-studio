# Research — 2026-11-25
- Installed llguidance 1.9.1 contains hf.from_tokenizer, LLMatcher and mlx.apply_token_bitmask. Use the library's Metal mask rather than a custom kernel. Source: .venv/lib/python3.12/site-packages/llguidance/{hf.py,mlx.py,_lib.pyi}.
- mlx-lm 0.32.2 stream_generate accepts logits_processors; generate_step performs one-token lookahead, so the processor must allow terminal EOS after the matcher stops. Source: installed mlx_lm/generate.py.
- Decision: unified constrained JSON tool envelope, translated into OpenAI tool_calls, instead of family-specific marker parsing. This bounds function names/arguments across fast-tokenizer models and keeps model-specific tool markers out of the public protocol. Model semantic choices remain unguaranteed.
- Decision: bounded Schema keyword subset + Draft202012Validator final verification; reject unsupported constraints instead of ignoring them.
- Decision: buffer structured payloads before SSE emission; no speculative invalid tool parameters are sent to clients.
- Observed: the 0.5B model follows required/named constraints, but can repeat calls in auto after results. Test deterministic finalization with none; document model limitation without forcing auto semantics in server logic.
