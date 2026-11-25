# Validation
1. uv sync --locked; uv run pytest — protocol regressions and validation, no weights needed.
2. Already downloaded Qwen2.5-0.5B-Instruct-4bit: MLX_STUDIO_SMOKE=1 uv run pytest tests/test_agent_native.py -s.
3. Restart studio: uv run mlx-studio; load chat model in model library.
4. uv run python examples/agent_tools.py — client executes city lookup and obtains a final answer.
5. Use README JSON schema SDK example; parse returned content. Try unsupported keyword, wrong tool history, and max_tokens=1 to verify explicit errors.
6. Tools with stream:true: assemble delta.tool_calls by index and concatenate arguments; final finish_reason must be tool_calls. Structured stream errors must be handled explicitly.
