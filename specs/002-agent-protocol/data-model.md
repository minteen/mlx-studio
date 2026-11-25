# Agent protocol data model
Canonical constraints live in mlx_studio/protocol.py and structured.py.
- FunctionDefinition: name安全标识1–64字符、description最多4096字符、parameters对象Schema、strict布尔值。
- ToolDefinition: function类型，1–32个定义且名称唯一，总序列化大小最多64KB。
- ToolCall: id非空最多128字符；function.name、function.arguments（最多32768字符，合法有限JSON对象字符串）；一轮最多8个。
- Message: system/user/assistant/tool；content可空仅限有tool_calls的assistant。tool必须带tool_call_id与字符串content；历史调用ID全局唯一，每个结果恰好匹配一个未完成调用，所有调用结果齐全才可继续生成。
- Chat: tools可选；tool_choice auto/none/required/指定函数；parallel_tool_calls默认true。response_format支持text/json_object/json_schema。工具活跃时与JSON格式互斥。
- SchemaDefinition: name、schema、strict、description；Schema最多16KB、8层、256个节点，仅接受README列明的子集。
- GenerationError: message、code、status；区分编译/分词器不支持、截断和最终验证失败。
