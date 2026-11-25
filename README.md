# MLX Studio

面向 Apple Silicon 的中文本地 AI 工作台。只使用 Hugging Face **mlx-community** 下的模型，支持对话与文本 Embedding，并提供 OpenAI 兼容服务。

- 模型库：在线搜索、用途筛选、按仓库标识下载、任务状态、本地模型加载/卸载。
- 对话：逐步输出、多轮上下文、停止生成、系统提示词、温度和输出长度设置；浏览器保存会话。
- Embedding：批量文本向量、完整数值、维度、余弦相似度矩阵。
- 服务：推理开关、请求统计、调用示例、Bearer 密钥保护。

## 安装和运行

需要 Apple Silicon Mac、macOS 14 或更新、ARM Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。模型容量受可用内存限制。

```bash
git clone https://github.com/minteen/mlx-studio.git
cd mlx-studio
uv sync --locked
uv run mlx-studio
```

访问 [http://127.0.0.1:1234](http://127.0.0.1:1234)。静态前端与 API 同一服务，无需 Node、额外前端构建或云端账号。

1. 在「模型库」中下载 `mlx-community/Qwen2.5-0.5B-Instruct-4bit`（对话）与 `mlx-community/all-MiniLM-L6-v2-4bit`（Embedding）。
2. 下载完成后点击「加载模型」。对话与向量各可加载一个模型。
3. 进入对话或 Embedding 页面使用；「本地服务」提供调用地址与推理开关。

运行库支持的模型架构才可加载。搜索结果用途来自模型元信息与名称推测；按完整标识添加时需显式选择用途。不含图像、语音、训练或 RAG。

默认数据目录为当前工作目录的 `.data/`，可用 `--data-dir /absolute/path` 或 `MLX_STUDIO_DATA` 覆盖。下载后支持本地推理；重启保留模型文件与清单，驻留模型需重新加载。一个数据目录只允许一个进程，禁止多 worker 启动。会话保存在当前浏览器 localStorage，清理浏览器数据会删除记录。

## 局域网服务

```bash
export MLX_STUDIO_API_KEY='替换为你的长随机密钥'
uv run mlx-studio --host 0.0.0.0 --port 1234
```

非 loopback 监听必须配置密钥。打开控制台后用左下角钥匙按钮输入同一密钥；密钥仅保留在页面内存，刷新后需重输。`/api/*` 和 `/v1/*` 均需要 `Authorization: Bearer KEY`，`/health` 仅返回存活状态。默认绑定127.0.0.1；本地无密钥时仅供可信本机使用。

使用域名反向代理时设置 `MLX_STUDIO_ALLOWED_HOSTS=studio.example.com`，代理需传正确的 Host/协议头。公开互联网入口应配置 HTTPS；原生 MLX 需要运行在 Mac 上，Linux Docker 容器无法直接使用 macOS Metal。

管理接口与推理接口共用密钥，持有者可下载和加载模型、开关服务；请仅向可信用户提供。当前未完成生产公网安全审计与压力测试，安全边界及漏洞报告方式见 [SECURITY.md](SECURITY.md)。[.env.example](.env.example) 仅为环境变量参考，程序不会自动读取 `.env` 文件。

## 调用 API

只列出已加载模型。控制台「停止推理服务」使 `/v1/*` 返回503，HTTP管理界面仍运行；已接受的请求可以完成。

```bash
curl http://127.0.0.1:1234/v1/models

curl http://127.0.0.1:1234/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community/Qwen2.5-0.5B-Instruct-4bit","messages":[{"role":"user","content":"你好"}],"stream":true,"max_tokens":128}'

curl http://127.0.0.1:1234/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community/all-MiniLM-L6-v2-4bit","input":["机器学习","人工智能"]}'
```

启用密钥时为上述调用增加 `-H "Authorization: Bearer $MLX_STUDIO_API_KEY"`。

兼容 OpenAI Python 客户端的文本功能（客户端需另行安装）：

```python
import os
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:1234/v1",
                api_key=os.getenv("MLX_STUDIO_API_KEY", "local"))
result = client.chat.completions.create(
    model="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
    messages=[{"role": "user", "content": "你好"}], max_tokens=128)
print(result.choices[0].message.content)

vectors = client.embeddings.create(
    model="mlx-community/all-MiniLM-L6-v2-4bit",
    input=["hello", "world"], encoding_format="float")
print(len(vectors.data[0].embedding))
```

支持纯文本 system/user/assistant 消息，以及 assistant.tool_calls 和 tool 结果消息。支持 tools/tool_choice 与 JSON 结构化输出，见下文；不支持图像消息、base64 embedding、dimensions 或 Responses API。向量每批最多32条、每条8192字符，分词最多512 Token，超出部分截断。所有模型操作由固定线程串行执行，繁忙时后续请求等待。

完整管理协议：[contracts/api.md](specs/001-mlx-studio/contracts/api.md)，运行后也可访问 `/docs` 查看接口定义（实际调用仍需密钥）。

## macOS 后台部署

先确保 `uv sync --locked` 完成。生成配置不会自动修改系统服务：

```bash
uv run python scripts/launchd.py
```

生成 `dist/com.local.mlx-studio.plist`，使用绝对路径、固定工作目录、独立日志。脚本会将当前 `MLX_STUDIO_API_KEY` 和 `HF_ENDPOINT` 写入权限为600的配置。局域网后台服务可先设置密钥，再加 `--host 0.0.0.0`。

在你自己的终端安装和启动：

```bash
mkdir -p ~/Library/LaunchAgents
cp dist/com.local.mlx-studio.plist ~/Library/LaunchAgents/
chmod 600 ~/Library/LaunchAgents/com.local.mlx-studio.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.mlx-studio.plist
```

用户登录后自动启动、进程退出后自动重启。启动前应停止终端内同端口的服务。此配置为当前登录用户的 LaunchAgent，Mac 休眠期间不提供服务。日志位于 `.data/logs/`。

停止并移除自启：

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.local.mlx-studio.plist
```

模型加载也可以由脚本调用管理 API，例如：

```bash
curl http://127.0.0.1:1234/api/models/load \
  -H 'Content-Type: application/json' \
  -d '{"id":"mlx-community/Qwen2.5-0.5B-Instruct-4bit","kind":"chat"}'
```

## 验证与开发

```bash
uv run pytest
uv run ruff check mlx_studio scripts tests examples
node --check mlx_studio/static/app.js
MLX_STUDIO_SMOKE=1 uv run pytest tests/test_native.py -s
```

默认测试使用隔离目录和测试运行器，不下载权重。真实验证会下载上面的两个小模型并验证对话、SSE、384维向量和服务开关；请先停止使用同一数据目录的服务，或者指定 `MLX_STUDIO_DATA=/tmp/mlx-smoke`。

下载网络问题可在启动前设置 `HF_HUB_DISABLE_XET=1` 改用标准 HTTP；`HF_ENDPOINT` 可配置你信任的镜像。下载失败可直接重试，已有文件会复用。不要关闭证书校验。模型加载失败时检查用途、架构支持和内存；更大模型可能需要先手动卸载现有模型。

项目规格与历史验证记录见 [specs/001-mlx-studio](specs/001-mlx-studio/) 和 [specs/002-agent-protocol](specs/002-agent-protocol/)。验证记录只代表所注明日期的测试结果，不描述当前运行状态。GitHub CI 在 Linux 上验证协议、校验和打包；Apple Silicon 原生推理测试需要在 Mac 上显式运行。

### 提交与发布

提交前检查 `git status --short` 和 `git diff --cached`，确认没有模型、数据、日志、生成的 launchd 配置、凭据或私人截图。`.agents/` 和 `.specify/` 包含共享开发工作流；其中被忽略的本机状态不应加入版本控制。`uv.lock` 随源码提交，以便使用 `uv sync --locked` 重现依赖。

`uv build` 生成源码包与 wheel；源码包使用显式的文件范围，wheel 包含 Python 包与静态前端。发布前应在干净环境中安装并检查页面和 API，不依赖开发机器已有的模型或配置。

项目代码采用 [MIT 许可证](LICENSE)。开发模板的上游许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。下载的模型权重、模型相关文件和第三方依赖适用各自的许可证，使用或再分发前应检查对应条款。项目与 Hugging Face、OpenAI 及 Apple 无隶属关系。

## Agent 工具调用与 JSON 输出

现在 `/v1/chat/completions` 支持：

- `tools`：1–32个 function 定义，名称唯一；参数根类型为 object。
- `tool_choice`：`auto`（默认）、`none`、`required` 或 `{"type":"function","function":{"name":"工具名"}}`。
- `parallel_tool_calls`：默认true，每轮最多8个；false时最多1个。这控制返回调用数量，不代表服务执行工具。
- assistant 的 `tool_calls`、可空 `content`，以及 tool 的 `tool_call_id` 和字符串 `content`。继续生成前必须回传该轮全部工具结果，ID不可重复。

服务通过 **llguidance 约束解码**生成工具决策及参数，再转换为 OpenAI 格式。这里使用统一 JSON 工具协议，而非各模型私有的工具标签解析。工具历史由服务转换为文本聊天模板；工具名与参数受Schema约束。模型是否选对工具、是否利用好结果仍取决于模型能力。

服务不执行工具。你的 Agent 收到 `finish_reason: "tool_calls"` 后，执行已声明的工具，将原样 assistant 消息和逐条 tool 结果加入 messages，再次请求。

可运行的完整例子（使用Python标准库，无需额外SDK）：

```bash
uv run python examples/agent_tools.py
```

先在控制台加载对话模型。可用 `MLX_STUDIO_MODEL`、`MLX_STUDIO_BASE_URL` 和 `MLX_STUDIO_API_KEY` 配置连接。示例的城市查询在客户端执行：第一轮required调用工具，第二轮none生成最终回答，另有最多4轮的保护。复杂Agent可以改为auto并自行设置循环上限。实测0.5B模型在auto模式可能重复调用；参数结构可靠不等于工具决策语义可靠。

### JSON 输出

`response_format={"type":"json_object"}` 生成合法JSON对象。指定字段结构时：

```python
# client 为前文创建的 OpenAI 客户端
result = client.chat.completions.create(
    model="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
    messages=[{"role": "user", "content": "Extract the city from: I live in Paris."}],
    temperature=0, max_tokens=256,
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "city_result", "strict": True,
            "schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False
            }
        }
    })
print(result.choices[0].message.content)
```

支持的 Schema 关键字为 `type`、`properties`、`required`、布尔 `additionalProperties`、`items`、`minItems`、`maxItems`、`enum`、`const`、`anyOf`、`title`、`description`。单个Schema最多16KB、8层嵌套、256个节点。`$ref`、`pattern`、`minimum`、`maxLength` 等当前明确拒绝；不能把任意Pydantic导出的Schema直接视为兼容。Schema还须通过llguidance编译；无法编译或带不支持约束警告时返回400。

`strict:false` 不会关闭约束或最终校验。默认参数Schema没有设置 `additionalProperties:false` 时，允许额外参数；需要精确字段时应显式设置。工具调用和JSON响应格式不能同时开启；如需保留工具定义但只返回JSON，请设置 `tool_choice:"none"`。

### 流式与错误约定

普通对话继续逐Token输出。**工具调用与JSON结果先在服务端缓冲并校验，再以SSE分片发送**，不承诺实时逐Token结构化输出。工具片段为 `delta.tool_calls`，首片包含index/id/type/name，后续片段携带arguments字符串；客户端按index拼接。JSON结果在 `delta.content` 中拼接。

- 不合法协议、未知工具、错误历史或不支持的Schema关键字：422。
- 不支持的分词器或文法编译失败：400，`unsupported_tokenizer` / `unsupported_schema`。
- 达到输出长度上限：422，`structured_output_incomplete`，不返回半成品成功结果。
- 最终结构校验失败：422，`structured_output_error`。
- 已开始SSE的生成失败：发送带code的error事件及 `[DONE]`，不发送成功finish_reason。客户端必须检查error事件。

支持约束输出的前提是可适配的Hugging Face fast tokenizer。实测过仓库预置的Qwen2.5-0.5B模型；小模型不代表Agent语义可靠性，业务应选择合适的模型并限制工具循环次数。没有自动执行、自动修复参数或隐式重试。

验证新能力：

```bash
uv run pytest tests/test_agent.py
MLX_STUDIO_SMOKE=1 uv run pytest tests/test_agent_native.py -s
```

真实测试直接读取已下载的 `.data/models/Qwen2.5-0.5B-Instruct-4bit`，使用独立清单目录，不与正在运行的服务争用清单锁。
