# Tasks: MLX Studio
**Input**: spec.md, plan.md, research.md, data-model.md, contracts/api.md

## Phase 1: Setup
- [X] T001 创建 Python 包、依赖和忽略配置于 pyproject.toml、.gitignore、mlx_studio/__init__.py

## Phase 2: Foundation
- [X] T002 实现固定线程运行器与有界流桥接于 mlx_studio/runtime.py
- [X] T003 实现同源 API、密钥鉴权和统一错误于 mlx_studio/app.py

## Phase 3: US1 模型管理
- [X] T004 [US1] 实现模型下载与原子持久化于 mlx_studio/catalog.py，遵循 data-model.md Model.id/kind/status/path/bytes/error
- [X] T005 [US1] 实现加载卸载和搜索接口于 mlx_studio/app.py、mlx_studio/runtime.py
- [X] T006 [US1] 实现模型搜索、筛选、下载状态与本地列表于 mlx_studio/static/app.js

## Phase 4: US2 对话
- [X] T007 [US2] 实现 OpenAI 流式/非流式对话于 mlx_studio/app.py、mlx_studio/runtime.py，遵循 data-model.md ChatRequest.messages/max_tokens/temperature/top_p
- [X] T008 [US2] 实现会话持久化、多轮上下文及停止于 mlx_studio/static/app.js，遵循 data-model.md Conversation

## Phase 5: US3 向量
- [X] T009 [US3] 实现批量向量接口于 mlx_studio/app.py、mlx_studio/runtime.py，遵循 data-model.md EmbeddingRequest.input/encoding_format
- [X] T010 [US3] 实现向量及相似度矩阵展示于 mlx_studio/static/app.js

## Phase 6: US4 服务
- [X] T011 [US4] 实现服务开关、统计、CLI 参数与部署配置于 mlx_studio/app.py、mlx_studio/cli.py、scripts/launchd.py
- [X] T012 [US4] 实现服务状态与调用示例于 mlx_studio/static/app.js

## Phase 7: Polish & Validation
- [X] T013 完成中文布局和响应式样式于 mlx_studio/static/index.html、mlx_studio/static/style.css
- [X] T014 验证 API 错误、鉴权、状态机与协议于 tests/test_api.py
- [X] T015 实际小模型验证于 tests/test_native.py，记录验证结果于 specs/001-mlx-studio/validation.md
- [X] T016 完成安装与后台部署文档于 README.md

## Dependencies & Execution Order
T001 → T002/T003 → US1 → US2 → US3 → US4 → polish。US2 和 US3 均可独立用驻留模型验证；US4 停止后应503。MVP是 US1，交付包含全部四个故事。
共16项；US1三项、US2两项、US3两项、US4两项、基础/验证七项。不同文档和样式可并行，无需额外代理。每项均有ID、checkbox、具体文件；故事阶段有US标签。
