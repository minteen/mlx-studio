# Plan
2026-11-25。扩展现有FastAPI/MLX线程服务。协议与验证放protocol.py；约束解码放structured.py；runtime.py串接；app.py输出OpenAI格式。
采用llguidance原生MLX掩码 + JSON Schema生成统一工具决策结构，适配普通文本模型，避免依赖各模型的私有工具标签。工具定义作为系统协议提示，历史工具调用和结果转换为文本；强制/指定工具由文法保证。jsonschema独立验证最终结果。所有MLX与matcher状态均在固定线程，分词器包装按模型缓存，每个请求新建matcher。
结构化结果缓冲验证后分片交付，普通文本仍逐token返回。不支持的Schema关键字提前拒绝，不忽略约束。约束支持深度/大小上限。流中错误以error事件返回，不发送伪完成结果。
Constitution现为未填模板；无扩展hooks。验证包括API协议、真实Metal解码、SDK样式多轮工具消息、流取消与旧接口回归。
