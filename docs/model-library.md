# 模型库管理

模型库保留现有 `mlx-community` 限制，新增以下同源管理接口。启用密钥时均需 Bearer 认证。

| 接口 | 参数 | 行为 |
| --- | --- | --- |
| `GET /api/models/info?id=mlx-community/NAME` | 查询参数 `id` | 返回 `id`、`total_bytes`、`revision`；元数据缓存5分钟，不下载权重 |
| `POST /api/models/download` | `{"id":"mlx-community/NAME","kind":"chat"}` | 返回202，任务排队；向量模型使用 `embedding` |
| `POST /api/models/cancel` | `{"id":"mlx-community/NAME"}` | 返回202，设置取消信号，保留已下载内容 |
| `POST /api/models/delete` | `{"id":"mlx-community/NAME"}` | 删除本地文件并移除清单，返回 `id` 和 `deleted_bytes` |

`GET /api/models` 继续返回本地模型数组，每条记录包含：

- `status`：`queued`、`downloading`、`cancelling`、`cancelled`、`ready` 或 `error`。
- `bytes`：模型目录的普通文件及未完成下载文件的逻辑大小；不含下载元数据，不跟随符号链接。不是磁盘块占用或运行内存。
- `total_bytes`：远端仓库文件总大小；旧记录或元数据不完整时可能缺省或为 `null`。界面支持按需查询。
- `progress`：根据本地文件大小估算的0–100整数；总量未知时为 `null`，任务成功前最多99。已有其他版本文件时可能偏高。
- `speed_bps`：最近采样的本地文件增长速度（字节/秒），不是网络吞吐量；重启或停止后为0。
- `revision`：下载绑定的仓库提交；取消或失败重试沿用同一版本。
- `error` / `error_code`：可展示的错误说明及稳定分类，不包含原始异常中的路径、令牌或URL。

下载使用独立子进程执行 Hugging Face snapshot 下载，避免取消仅改变界面却继续消耗网络。取消时终止传输子进程并等待其退出；若仍在请求远端元数据，可能需要等待该请求结束或超时。元数据读取超时设为15秒。排队任务取消后无需下载即可结束。服务正常关闭也会取消任务；异常退出遗留的活动状态在下次启动标记为中断，可重试。

删除操作与模型加载、卸载共用推理工作队列，并在执行时检查驻留状态。已加载模型或活动下载返回409，必须先卸载或取消。目录缺失时仍可删除清单记录；文件删除失败时保留错误记录供重试。删除不修改浏览器会话。

`GET /api/status` 增加 `operations`，以模型标识为键，值为 `loading`、`unloading` 或 `deleting`；操作完成或失败后移除。请求已接受但仍等待推理线程时，也会保留对应状态。并发提交同一模型的管理操作返回409。

错误分类包括 `disk_full`、`access_denied`、`not_found`、`network_error`、`download_error`、`interrupted`、`delete_failed`；加载失败可返回 `out_of_memory`、`unsupported_model`、`model_load_error`。磁盘空间预检不能保证下载期间空间始终充足，实际写入失败仍会报告错误。

## 验证

`uv run pytest -q` 包含模型管理回归测试，无需网络或权重，覆盖删除范围、符号链接保护、下载取消与重试、真实子进程回收、错误脱敏、元数据大小和版本、空间不足、管理接口认证和并发操作保护。原生推理测试仍需单独启用。
