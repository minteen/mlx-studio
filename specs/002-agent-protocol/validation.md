# Validation — 2026-11-25

以下为当日的历史验证记录，所述本机服务与部署状态不代表当前环境。

## Results
- `pytest -q`: **39 passed, 2 skipped**。跳过项为显式启用的原生模型测试，非功能失败。保留现有Starlette/httpx弃用警告。
- `MLX_STUDIO_SMOKE=1 uv run pytest tests/test_agent_native.py -s -q`: **1 passed**，3.29秒。
- `ruff check mlx_studio tests examples scripts`通过；`node --check mlx_studio/static/app.js`通过。
- 实际HTTP服务启动并加载已下载chat模型；`uv run python examples/agent_tools.py`运行成功：客户端执行city_info(Paris)，收到France/Europe/Paris，再回传，模型回答“Paris is in the country of France, and it is in the time zone of Europe/Paris.”。

## Native inference evidence
- 模型：mlx-community/Qwen2.5-0.5B-Instruct-4bit；同一固定MLX线程，使用已下载文件，无新增权重下载。
- JSON Schema真实输出：{"city":"Paris","days":[1,2]}；嵌套数组、枚举和必填字段约束通过。
- required真实调用：get_weather，arguments为{"city":"Paris"}，finish_reason=tool_calls。
- tool回传后none模式真实回答：Paris is 17 degrees Celsius and sunny.
- named+stream成功重组参数并以tool_calls结束；json_object通过；max_tokens=1明确返回structured_output_incomplete。

## Regression coverage
旧API/模型管理/鉴权/线程取消14项保持通过。新增测试验证：工具片段重组、中文长参数、工具结果ID闭环、required/named拒绝普通回答、auto普通回答与多调用、parallel=false上限、嵌套Schema、JSON流重组、SSE错误无成功结束帧、非法请求/历史/参数、未知工具、Schema子集与非有限数字、截断处理。

## Resolved and remaining limits
- 修复MLX一Token前瞻计算在grammar完成后仍消费EOS导致的状态错误；完成后只允许终止Token。
- 0.5B模型在auto模式接收结果后可能重复调用工具。服务不强制改变auto决策；真实测试验证其返回协议、工具名和参数约束，none模式验证最终回答确实包含结果事实。该现象已在README记录，示例使用required→none确定流程。
- 结构化SSE先缓冲验证后分片，不是实时逐Token输出；普通文本流不变。
- 支持README列明的Schema子集；不保证任意模型分词器、任意Schema和Agent语义质量。
- 本机127.0.0.1:1234保留更新后的试用服务，chat模型已加载。未注册系统自启。
