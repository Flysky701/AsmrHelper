# Task Execution V1

更新时间：2026-08-19

本文收口 AsmrHelper 的长耗时任务执行边界。它复用现有 `TaskRegistry`、`TaskDispatcher`、`PipelineTaskOrchestrator` 和 `RuntimeRouter`，并以持久化 `BatchRun` 聚合多个普通 Pipeline Task；不引入新的持久执行队列或分布式调度平台。

## 1. 统一入口

所有长耗时能力先创建 Task V1，再由同一进程内 `TaskDispatcher` 执行：

| task_type | 执行器 | 产物归属 |
| --- | --- | --- |
| `pipeline` | `PipelineTaskOrchestrator` → `PipelineService` | 每个 Artifact 的 `task_id`；完成任务的 `artifact_set_id` 为任务 ID |
| `tool.separate/convert/split/translate_subtitle/volume_preview` | `ToolRegistry` → `AudioToolService` | 每个 Artifact 的 `task_id` |
| `subtitle.script_to_vtt` | `ScriptSubtitleService` → `core.subtitles` | 自动生成的 TXT/VTT/SRT/LRC 只归属创建它的 Task |
| `model_install` | `ModelService` → `ModelInstaller` | 状态与 RuntimeEvent；安装文件不伪装成音频 Artifact |
| `voice.design/clone/preview` | `VoiceService` → `RuntimeRouter` → `qwen_tts` Worker | 参考音频、prompt cache 或 preview WAV 的 `task_id` |

`ExecutorRegistry` 在提交时拒绝未知任务类型。已声明但尚未绑定 callable 的类型也不能被 Dispatcher 执行：它会在执行边界明确失败，不会永久停留在 `pending`。

通用 `POST /api/v1/tasks` 和 `POST /api/v1/tasks/batch` 是“创建并提交”入口，不是只创建 TaskSpec 的存根接口；成功创建的每一项会立即交给 Dispatcher。领域入口仍须先完成各自的输入、readiness 和资源校验。

批量产品入口为 `POST /api/v1/batch-runs`。`BatchRun` 只拥有稳定 `batch_id`、输入项、子任务 ID、聚合进度和批次控制状态，不成为第二种 Pipeline 执行器。每个文件仍创建普通 `pipeline` Task，沿用原有 readiness、取消、错误和 Artifact 归属。批量并行度只决定同时提交多少个子任务，实际执行容量仍由共享 Dispatcher 限制。

Tool 领域入口 `POST /api/v1/tool-runs/tasks` 同样是“创建并提交”：响应返回 Task 快照，执行在后台继续。旧 `POST /api/v1/tool-runs` 同步执行入口已删除，避免已提交任务被再次接管。

模型安装的默认 `POST /api/v1/models/{model_id}/install` 返回标准 TaskStatus `201`，资源页提交后进入 TaskCenter，由统一查询、取消和重试契约管理。显式 `sync=true` 只作为诊断兼容入口，仍会阻塞请求且不属于桌面产品主路径。

字幕工坊的长耗时台本处理使用 `POST /api/v1/subtitles/script-to-vtt/tasks`。未显式指定输出时，后端根据台本路径生成 `_cleaned.txt` 或 `_aligned.<fmt>`；进度阶段、取消、错误和 Artifact 归属均由 Task V1 管理。字幕翻译页面直接复用 `tool.translate_subtitle`，不再通过同步字幕接口伪装为后台任务。

Voice Design、Clone 与 Preview 的正式 HTTP 入口也返回 TaskStatus `201`，不等待 Qwen Worker 完成。桌面端提交后进入 TaskCenter；生成的参考音频、prompt cache 和试听 WAV 通过统一 TaskResult 获取。片段分析仍是克隆表单的同步结构化查询，不伪装成可取消后台任务。

ASR、LLM 与 TTS 的单次直连接口是底层同步诊断面，不是桌面产品任务入口；它们用于 Provider 校准和真实推理探测，不承诺 Task 生命周期。任何需要进度、取消、重试和 Artifact 归属的用户操作必须走 Pipeline、Tool 或 Voice Task。

## 2. 状态契约

- 创建时为 `pending`；Dispatcher 只允许从 `pending` 开始一次，执行器退出前保持 `running`。
- `completed`、`failed`、`cancelled`、`skipped` 是终态。终态的生命周期字段、错误、阶段、进度和产物关联不可再修改；审阅字段可以独立更新。
- 取消是请求语义：`request_cancel` 只设置取消事件并返回仍为 `running` 的快照；执行器退出后 Dispatcher 才写入最终 `cancelled`。
- 异常统一落在 `failed`，`error.stage` 使用执行时最后已知阶段，`error.code` 和 `detail` 保留可诊断信息。
- 产物由产物服务以 `task_id` 注册；失败和取消任务不继承其他任务的产物。
- 重试创建新 Task，原任务保持终态，新 Task 的 `retry_of_task_id` 指向原任务。重启时继续清理未完成任务；恢复的 Pipeline、Tool、模型安装和 Voice 终态历史任务均只读。
- BatchRun 的失败项重提会依据批次保存的输入与执行配置创建新的 Pipeline Task，并把新 task_id 追加到对应条目历史；成功项不会重复执行。APP 重启时未完成子任务仍按 Task V1 清理，批次标记为 `interrupted`，用户可显式重提其中失败项，不伪装成断点续跑。

## 3. Pipeline 与 Worker 边界

`POST /api/v1/pipeline-runs`、Pipeline V1 `execution_profile`、Pipeline 阶段处理逻辑和现有 Artifact 结构保持兼容。单文件 Pipeline、连续任务、失败隔离、取消后重提以及 Worker 异常后的人工重提均通过同一 Dispatcher 入口执行。

`RuntimeRouter` 继续将 Qwen ASR/TTS 以及 Voice Design/Clone/Preview 放到隔离 Worker。Worker 异常会清理 request/response 交换文件并使当前任务明确失败；本版本不自动重启 Worker。

## 4. 明确不做

本版本不引入 `root_task_id`、`executor_version`、CPU/GPU/网络资源标签、持久执行队列或分布式调度。`BatchRun` 仅为持久聚合与控制事实，不能绕过 TaskDispatcher，也不承诺进程重启后继续执行未完成音频。
