# Task Execution V1

更新时间：2026-08-07

本文收口 AsmrHelper 的长耗时任务执行边界。它复用现有 `TaskRegistry`、`TaskDispatcher`、`PipelineTaskOrchestrator` 和 `RuntimeRouter`，不引入新的持久队列、BatchRun 聚合实体或分布式调度平台。

## 1. 统一入口

所有长耗时能力先创建 Task V1，再由同一进程内 `TaskDispatcher` 执行：

| task_type | 执行器 | 产物归属 |
| --- | --- | --- |
| `pipeline` | `PipelineTaskOrchestrator` → `PipelineService` | 每个 Artifact 的 `task_id`；完成任务的 `artifact_set_id` 为任务 ID |
| `tool.separate/convert/split/translate_subtitle/volume_preview` | `ToolRegistry` → `AudioToolService` | 每个 Artifact 的 `task_id` |
| `model_install` | `ModelService` → `ModelInstaller` | 状态与 RuntimeEvent；安装文件不伪装成音频 Artifact |
| `voice.design/clone/preview` | `VoiceService` → `RuntimeRouter` → `qwen_tts` Worker | 参考音频、prompt cache 或 preview WAV 的 `task_id` |

`ExecutorRegistry` 在提交时拒绝未知任务类型。已声明但尚未绑定 callable 的类型也不能被 Dispatcher 执行：它会在执行边界明确失败，不会永久停留在 `pending`。

通用 `POST /api/v1/tasks` 和 `POST /api/v1/tasks/batch` 是“创建并提交”入口，不是只创建 TaskSpec 的存根接口；成功创建的每一项会立即交给 Dispatcher。领域入口仍须先完成各自的输入、readiness 和资源校验。

Tool 领域入口 `POST /api/v1/tool-runs/tasks` 同样是“创建并提交”：响应返回 Task 快照，执行在后台继续。`POST /api/v1/tool-runs` 保留为已有 Task 的兼容执行入口，桌面端不需要先创建再同步调用它。

## 2. 状态契约

- 创建时为 `pending`；Dispatcher 只允许从 `pending` 开始一次，执行器退出前保持 `running`。
- `completed`、`failed`、`cancelled`、`skipped` 是终态。终态的生命周期字段、错误、阶段、进度和产物关联不可再修改；审阅字段可以独立更新。
- 取消是请求语义：`request_cancel` 只设置取消事件并返回仍为 `running` 的快照；执行器退出后 Dispatcher 才写入最终 `cancelled`。
- 异常统一落在 `failed`，`error.stage` 使用执行时最后已知阶段，`error.code` 和 `detail` 保留可诊断信息。
- 产物由产物服务以 `task_id` 注册；失败和取消任务不继承其他任务的产物。
- 重试创建新 Task，原任务保持终态，新 Task 的 `retry_of_task_id` 指向原任务。重启时继续清理未完成任务；恢复的 Pipeline、Tool、模型安装和 Voice 终态历史任务均只读。

## 3. Pipeline 与 Worker 边界

`POST /api/v1/pipeline-runs`、Pipeline V1 `execution_profile`、Pipeline 阶段处理逻辑和现有 Artifact 结构保持兼容。单文件 Pipeline、连续任务、失败隔离、取消后重提以及 Worker 异常后的人工重提均通过同一 Dispatcher 入口执行。

`RuntimeRouter` 继续将 Qwen ASR/TTS 以及 Voice Design/Clone/Preview 放到隔离 Worker。Worker 异常会清理 request/response 交换文件并使当前任务明确失败；本版本不自动重启 Worker。

## 4. 明确不做

本版本不引入 `root_task_id`、`executor_version`、CPU/GPU/网络资源标签、`BatchRun` 聚合实体或分布式队列；同步 batch 聚合接口继续由每个独立 Pipeline task 组成。
