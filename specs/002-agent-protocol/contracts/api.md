# Chat API additions
POST /v1/chat/completions accepts OpenAI function tools and response_format.
Request examples and precise limits: README.md → Agent工具调用与JSON输出。
- required/named只返回tool_calls，auto可返回content或tool_calls，none不调用。
- arguments是JSON字符串；assistant.content调用时可空；finish_reason为tool_calls。
- 服务不执行工具。回传assistant.tool_calls及tool.tool_call_id/content后继续请求。
- JSON与工具约束生成使用llguidance，所有成功结果再由jsonschema验证；工具选择仍由模型决定。
- 流式结构化结果先缓冲验证，随后发送delta.tool_calls或delta.content；参数按index重组。最后finish_reason + [DONE]。
- 错误响应为error.message/type/code；422参数或输出错误，400分词器/编译不支持。SSE开始后的失败为error事件+[DONE]，没有成功finish_reason。
- 旧文本流、向量、模型管理及鉴权协议保持兼容。
