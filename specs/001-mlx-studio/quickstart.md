# Validation guide
1. Apple Silicon macOS >=14，uv sync；uv run mlx-studio。
2. 浏览器打开 http://127.0.0.1:1234；模型库下载两个预置小模型，观察完成状态。
3. 加载 chat 后发送两轮对话，停止一次生成，刷新验证历史。
4. 加载 embedding 后运行三条文本，核对384维和3×3矩阵。
5. 服务页面复制示例，用 curl 调用 /v1/models、非流式/流式 chat 和 embeddings。
6. 停止服务，新请求503；恢复后可调用；卸载后模型列表移除。
7. uv run pytest；MLX_STUDIO_SMOKE=1 uv run pytest tests/test_native.py -s 进行真实下载推理。
8. uv run python scripts/launchd.py 生成后台配置，按 README 安装启动；脚本不会自行注册。
详见 contracts/api.md 和仓库 README.md。
