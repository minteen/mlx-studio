# Feature Specification: MLX Studio

**Feature Branch**: 无（目录尚未初始化 Git）
**Created**: 2026-11-24
**Status**: Implemented; validation recorded in validation.md
**Input**: 基于 specify 实现类似 LM Studio 的可视化软件，仅支持 MLX Community 的对话和 Embedding 模型，并可部署成服务。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 模型管理 (Priority: P1)
用户搜索 MLX Community 模型，按对话或向量用途筛选，下载并加载、卸载本地模型。
**Why this priority**: 本地模型是推理前提。
**Independent Test**: 下载小模型，重启仍能发现，加载和卸载状态真实可见。
**Acceptance Scenarios**:
1. **Given** 联网，**When** 搜索，**Then** 仅返回 mlx-community 模型及用途。
2. **Given** 未下载模型，**When** 下载，**Then** 显示下载中、完成或失败，失败可重试。
3. **Given** 已下载模型，**When** 加载或卸载，**Then** 显示真实状态，不支持的架构给出错误。

### User Story 2 - 本地对话 (Priority: P1)
用户选择对话模型，设置系统提示、温度和输出长度，进行流式多轮对话。
**Why this priority**: 核心使用入口。
**Independent Test**: 连续两轮提问，第二轮保留上下文；刷新后记录存在。
**Acceptance Scenarios**:
1. **Given** 已加载对话模型，**When** 提问，**Then** 逐步显示文本及完成状态。
2. **Given** 正在生成，**When** 停止，**Then** 保留收到内容并释放请求资源。
3. **Given** 多个会话，**When** 新建、切换或删除，**Then** 各自历史独立且变更持久保存。

### User Story 3 - Embedding 调试 (Priority: P1)
用户加载向量模型，为多条文本生成向量，查看维度、数值和余弦相似度。
**Why this priority**: 用户明确要求向量模型。
**Independent Test**: 三条文本生成三条维度一致的有限向量和相似度矩阵。
**Acceptance Scenarios**:
1. **Given** 已加载向量模型，**When** 输入文本列表，**Then** 显示逐条向量、维度和相似度。
2. **Given** 模型用途不符，**When** 请求推理，**Then** 返回可理解错误。

### User Story 4 - 部署服务 (Priority: P2)
用户启停推理服务，查看地址和示例，通过通用客户端调用模型。
**Why this priority**: 供其他应用集成和长期运行。
**Independent Test**: 外部客户端列出模型、发送对话与向量请求；停止后推理被拒绝，控制台仍可用。
**Acceptance Scenarios**:
1. **Given** 驻留模型，**When** 启动服务，**Then** 展示真实状态及调用示例。
2. **Given** 配置密钥，**When** 密钥错误，**Then** 拒绝推理与管理操作。
3. **Given** 后台部署配置，**When** 按文档安装运行，**Then** 无需持续打开终端即可访问。

### Edge Cases
- 网络中断、仓库不存在、磁盘不足：下载失败保留错误，可重试。
- 非 mlx-community 标识、本地路径和用途不符：拒绝请求。
- 内存不足和架构不支持：显示错误，驻留状态不伪造。
- 并发推理与模型切换：串行模型操作，避免使用已卸载模型。
- 空输入、超长输入、非法参数：验证错误；客户端断开后结束生成。
- 服务停止或未加载模型：明确拒绝，不生成模拟结果。

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: 只接受 mlx-community 模型标识，支持搜索、用途筛选与显式添加。
- **FR-002**: 后台下载不阻塞界面，展示状态、已下载字节和错误；本地模型元信息持久保存。
- **FR-003**: 对话与向量各可驻留一个模型，支持加载与卸载，错误可见。
- **FR-004**: 对话支持流式输出、多轮上下文、系统提示、温度、输出长度及停止。
- **FR-005**: 浏览器本地保存会话，支持新建、切换、删除。
- **FR-006**: 批量文本向量支持维度、数值及余弦相似度矩阵展示。
- **FR-007**: 提供兼容 OpenAI 格式的模型列表、流式/非流式对话及向量服务。
- **FR-008**: 控制台支持启停推理，展示健康状态、请求统计和调用示例。
- **FR-009**: 默认仅监听本机；非本机监听必须配置密钥，推理及管理操作均受保护。
- **FR-010**: 提供 Apple Silicon macOS 安装、运行、后台服务部署说明与配置生成工具。
- **FR-011**: 中文控制台；本地推理不上传文本，错误不暴露密钥。

### Key Entities
- **模型**: 仓库标识、用途、目录、状态、大小、错误。
- **下载任务**: 模型、运行状态、字节数、失败原因。
- **会话**: 标题、消息、时间与生成设置，在浏览器保存。
- **服务状态**: 推理开关、驻留模型、运行时间、请求及失败数量。

## Success Criteria *(mandatory)*

### Measurable Outcomes
- **SC-001**: 已下载模型后，用户 3 分钟内完成加载并获得首次回复。
- **SC-002**: 三条文本返回三条维度一致且所有值有限的向量。
- **SC-003**: 搜索、下载、对话、向量、服务启停五个流程均有可执行验证步骤，无占位成功结果。
- **SC-004**: 服务启停后 2 秒内，新请求得到与界面状态一致的响应；已有请求可完成。
- **SC-005**: 重启后本地模型可发现；刷新后会话记录保留。

## Assumptions
- 首版为本机浏览器控制台，运行于 Apple Silicon macOS；无需桌面应用打包。
- 下载来自 Hugging Face mlx-community，需网络；推理在本地，支持已下载模型离线加载。
- 仅支持运行库支持的文本模型，不保证组织内所有架构兼容；不含多模态、训练、RAG、多用户权限系统。
- 使用小模型进行首次真实验证；实际速度和容量取决于硬件。
- 密钥通过环境配置，局域网访问通过启动参数开启；公网使用需外部 TLS 入口。
