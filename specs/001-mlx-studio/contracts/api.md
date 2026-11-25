# API Contract
同源 JSON；配置密钥后除静态页面与 /health 外均要求 Authorization: Bearer TOKEN。
- GET /health → {status:ok}，不暴露模型或密钥。
- GET /api/status → enabled/loaded/requests/errors/uptime/platform。
- GET /api/models → 持久模型清单。
- GET /api/search?q=&kind=chat|embedding → mlx-community 搜索结果。
- POST /api/models/download {id,kind} → 202，下载异步执行，可通过模型列表观察字节数。
- POST /api/models/load {id,kind}；POST /api/models/unload {kind}。
- POST /api/service {enabled:bool} → 推理开关，不停止 HTTP。
- GET /v1/models → OpenAI list，仅列出已加载模型。
- POST /v1/chat/completions {model,messages,temperature,top_p,max_tokens,stream} → 标准 completion 或 SSE chunks + [DONE]；finish_reason stop/length。
- POST /v1/embeddings {model,input,encoding_format:'float'} → list/embedding/index + usage。
错误统一为 {error:{message,type,code}}，验证422、鉴权401、状态409/503、推理500。推理关闭时 /v1/* 均503。界面使用同一推理端点。
