# Feature Specification: Agent Tool Calling and Structured Output
**Created**: 2026-11-25
**Feature Branch**: 无（当前未使用Git）
**Status**: Implemented; see validation.md
**Input**: 为个人 Agent 应用补齐 Tool Calling 和 JSON 输出。

## User Scenarios & Testing
### US1 工具调用闭环 (P1)
Agent声明工具，收到工具名和参数，自行执行，再回传结果以获得回答。
**Why this priority**: Agent需通过标准协议调用自己的工具。
**Independent Test**: 一个查询工具完成调用、回传、回答三步。
**Acceptance**: auto可回答或调用；required必须调用；指定工具只调用该工具；none不调用；工具结果按ID关联。服务不执行工具。
### US2 结构化输出 (P1)
应用请求合法JSON或指定结构，用于解析计划和业务数据。
**Why this priority**: 机器消费输出需要可靠格式。
**Independent Test**: 生成包含必填字段、枚举和嵌套数组的结果并验证。
**Acceptance**: 结果符合请求结构；不支持的约束被明确拒绝；截断输出不伪装成功。
### US3 流式集成 (P2)
Agent用同一协议消费流式结果。
**Why this priority**: 与现有流式客户端集成。
**Independent Test**: 重组工具参数片段得到与非流式一致的调用结构。
**Acceptance**: 工具调用含稳定ID与索引、结束原因正确；取消释放工作线程；结构化输出验证通过后才发送有效载荷。
### Edge Cases
空工具列表、重复工具名、未知指定工具、非法参数、工具结果ID缺失/重复、截断、取消、不兼容分词器、复杂/外部引用结构、工具与输出结构冲突。

## Requirements
- FR001 支持tools、tool_choice、parallel_tool_calls、tool角色及tool_call_id。
- FR002 工具名和参数必须受声明约束，返回OpenAI兼容tool_calls；执行留给调用者。
- FR003 支持json_object和json_schema，使用生成约束并在输出后验证。
- FR004 不支持的结构、冲突请求、错误历史明确拒绝，不降级为普通文本。
- FR005 普通文本、向量、鉴权与原有接口保持兼容。
- FR006 流式tool_calls支持参数片段与正确结束原因；结构化输出可缓冲验证后交付。
- FR007 文档给出可执行Agent闭环与结构化输出示例。

## Key Entities
工具定义、工具选择、工具调用ID、工具结果、输出结构、生成错误。

## Success Criteria
- SC001 一个真实本地模型完成工具调用和结果回传。
- SC002 所有成功的结构化响应通过独立结构验证。
- SC003 非流式和重组后的流式工具名、参数、ID关系一致。
- SC004 旧接口测试全部保持通过。

## Assumptions
首版支持明确列出的结构子集；格式约束不保证语义正确；不实现工具执行器、MCP客户端或Agent编排；结构化流先验证再分片发送。
