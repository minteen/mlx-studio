# Validation results — 2026-11-24

以下为当日的历史验证记录，所述本机服务与部署状态不代表当前环境。

## Automated
- `pytest -q`: **14 passed, 1 skipped**（native 默认显式跳过）；存在一条 Starlette/httpx TestClient 弃用警告，不影响结果。
- `HF_HUB_DISABLE_XET=1 HF_HUB_DOWNLOAD_TIMEOUT=30 MLX_STUDIO_SMOKE=1 uv run pytest tests/test_native.py -s -q`: **1 passed**，54.44秒（包含下载和首次加载）。
- Qwen2.5-0.5B-Instruct-4bit 真实输出 `Hello!`；同一测试验证了标准 JSON 对话、SSE完成与推理关闭503。
- all-MiniLM-L6-v2-4bit 真实返回 **3 × 384** 向量，全部有限值。
- Ruff check通过；Python源码格式化；`node --check mlx_studio/static/app.js` 通过。
- 测试覆盖：API协议、token统计、输入校验、模型用途限制、服务开关、密钥/Origin/Host、清单恢复、数据目录锁、搜索SDK契约、推理线程亲和性和流式取消后的工作线程释放。

## Browser
- 桌面1440px与窄屏375px检查，无横向溢出；临时viewport已恢复。
- 在线 MiniLM 搜索返回4个 mlx-community 模型。
- 页面分别加载真实对话/向量模型，状态显示已加载。
- 中文提问获得流式回复，刷新后历史仍在；停止按钮保留已收到文本并回到可发送状态。
- 向量页面显示3条文本、384维、48输入Token和3×3余弦矩阵，完整向量可展开。
- 服务停止显示已停止，恢复正常；控制台持续可访问。
- 截图：`docs/screenshots/embedding.jpg`。

## Deployment
- `uv run python scripts/launchd.py` 成功生成 `dist/com.local.mlx-studio.plist`，未注册系统服务。
- 本机HTTP服务保持运行在127.0.0.1:1234，两个小模型已加载，可直接试用。
- 服务进程重启后保留本地文件与清单，驻留模型需重新加载（README已说明）。

## Issues resolved / limits
- 首次Xet下载遇到TLS超时；改标准HTTP后成功。未关闭证书校验。
- 当前huggingface-hub不再接受旧direction参数，已修复并加入回归测试。
- 仅支持运行库可加载的文本架构，不能保证整个组织中每个模型兼容。
- 尚未对大型模型、多客户端负载或生产公网环境进行压力测试。首版同一推理线程串行执行。
