# Task Execution V1

更新时间：2026-09-29

本文收口 AsmrHelper 的长耗时任务执行边界。它复用现有 `TaskRegistry`、`TaskDispatcher`、`PipelineTaskOrchestrator` 和 `RuntimeRouter`，并以持久化 `BatchRun` 聚合多个普通 Pipeline Task；不引入新的持久执行队列或分布式调度平台。

## 1. 统一入口

所有长耗时能力先创建 Task V1，再由同一进程内 `TaskDispatcher` 执行：

| task_type | 执行器 | 产物归属 |
| --- | --- | --- |
| `pipeline` | `PipelineTaskOrchestrator` → `PipelineService` | 每个 Artifact 的 `task_id`；完成任务的 `artifact_set_id` 为任务 ID |
| `tool.separate/convert/split/translate_subtitle/volume_preview` | `ToolRegistry` → `AudioToolService` | 每个 Artifact 的 `task_id` |
| `subtitle.script_to_vtt` | `ScriptSubtitleService` → `core.subtitles` | 自动生成的 TXT/VTT/SRT/LRC 只归属创建它的 Task |
| `model_install` | `ModelService` → `ModelInstaller` | 状态与 RuntimeEvent；安装文件不伪装成音频 Artifact |
| `speech.generate` | `SpeechService` → Speech Provider（本地模型使用隔离 Worker） | Task Artifact 与实验记录关联；正式配音文件位于所属 Pipeline 任务目录 |
| `speech.reference_analyze` | `SpeechService` → 字幕复用、停顿分析或显式 ASR | 分析进度与结构化候选结果，不自动保存声音库素材 |

`ExecutorRegistry` 在提交时拒绝未知任务类型。已声明但尚未绑定 callable 的类型也不能被 Dispatcher 执行：它会在执行边界明确失败，不会永久停留在 `pending`。

通用 `POST /api/v1/tasks` 和 `POST /api/v1/tasks/batch` 是“创建并提交”入口，不是只创建 TaskSpec 的存根接口；成功创建的每一项会立即交给 Dispatcher。领域入口仍须先完成各自的输入、readiness 和资源校验。

批量产品入口为 `POST /api/v1/batch-runs`。`BatchRun` 只拥有稳定 `batch_id`、输入项、子任务 ID、聚合进度和批次控制状态，不成为第二种 Pipeline 执行器。每个文件仍创建普通 `pipeline` Task，沿用原有 readiness、取消、错误和 Artifact 归属。批量并行度只决定同时提交多少个子任务，实际执行容量仍由共享 Dispatcher 限制。

Tool 领域入口 `POST /api/v1/tool-runs` 同样是“创建并提交”：响应返回 Task 快照，执行在后台继续。该入口只创建并提交后台任务，不同步执行，也不接管已有任务。

模型安装的默认 `POST /api/v1/models/{model_id}/install` 返回标准 TaskStatus `201`，资源页提交后进入 TaskCenter，由统一查询、取消和重试契约管理。显式 `sync=true` 只作为诊断兼容入口，仍会阻塞请求且不属于桌面产品主路径。

字幕工坊的长耗时台本处理使用 `POST /api/v1/subtitles/script-to-subtitle/tasks`。未显式指定输出时，后端根据台本路径生成 `_cleaned.txt` 或 `_aligned.<fmt>`；进度阶段、取消、错误和 Artifact 归属均由 Task V1 管理。字幕翻译页面直接复用 `tool.translate_subtitle`，不再通过同步字幕接口伪装为后台任务。

语音生成通过 `POST /api/v1/speech/experiments/{id}/generate` 返回 TaskStatus `202`，由 `speech.generate` 执行；结果关联实验候选与任务产物。声音库辅助选段通过 `/speech/references/analyze-tasks` 返回 `202` 的分析任务，并提供阶段进度、取消和结构化候选查询。现行能力按 Provider 声明开放，旧 `/voice/*`、`/tts/*` HTTP 入口已退出。

ASR、LLM 的单次直连接口是底层同步诊断面，不是桌面产品任务入口；它们用于 Provider 校准和真实推理探测，不承诺 Task 生命周期。旧 `/tts/synthesize` 不再挂载。需要任务进度、取消和结果归属的长耗时用户操作应走 Pipeline、Tool 或 Speech Task，是否可重试或恢复由具体任务契约决定。

## 2. 状态契约

- 创建时为 `pending`；Dispatcher 只允许从 `pending` 开始一次，执行器退出前保持 `running`。
- `completed`、`failed`、`cancelled`、`skipped` 是终态。终态的生命周期字段、错误、阶段、进度和产物关联不可再修改；审阅字段可以独立更新。
- 取消是请求语义：`request_cancel` 只设置取消事件并返回仍为 `running` 的快照；执行器退出后 Dispatcher 才写入最终 `cancelled`。
- 异常统一落在 `failed`，`error.stage` 使用执行时最后已知阶段，`error.code` 和 `detail` 保留可诊断信息。
- 产物由产物服务以 `task_id` 注册；失败和取消任务不继承其他任务的产物。
- 普通重试创建新 Task，原任务保持终态，新 Task 的 `retry_of_task_id` 指向原任务；重启加载的历史任务不支持普通重试。
- 重启时先将有恢复清单的未完成任务保留为 `failed / TASK_INTERRUPTED`，再清理其余未完成任务。符合条件的失败、取消或中断 Pipeline 可通过 `POST /tasks/{id}/resume` 创建新任务；输入、连接与检查点通过校验后复用已完成阶段，中断阶段重跑，不自动续跑或恢复阶段内部进度。
- BatchRun 的失败项重提会依据批次保存的输入与执行配置创建新的 Pipeline Task，并把新 task_id 追加到对应条目历史；成功项不会重复执行。APP 重启时批次标记为 `interrupted`，用户可显式重提失败项。子任务按上述 Pipeline 恢复规则保留或清理；批次重提与单个 Pipeline 的阶段恢复是不同操作。

## 3. Pipeline 与 Worker 边界

`POST /api/v1/pipeline-runs`、Pipeline V1 `execution_profile`、Pipeline 阶段处理逻辑和现有 Artifact 结构保持兼容。单文件 Pipeline、连续任务、失败隔离、取消后重提以及 Worker 异常后的人工重提均通过同一 Dispatcher 入口执行。

ASR 通过 `RuntimeRouter` 路由隔离 Worker；当前 Speech 本地模型由 Provider 启动隔离 Worker，远端 Provider 使用外部服务。旧 Voice 执行代码不属于正式 HTTP 入口。Worker 异常使当前任务明确失败，不自动重启 Worker。

## 4. 明确不做

本版本不引入 `root_task_id`、`executor_version`、CPU/GPU/网络资源标签、持久执行队列或分布式调度。`BatchRun` 仅为持久聚合与控制事实，不能绕过 TaskDispatcher，也不在进程重启后自动继续执行未完成音频；显式 Pipeline 阶段恢复不等于自动恢复执行队列。


## 5. 任务中心的节点状态显示

V2 任务的可显示节点来自其冻结 `execution_profile.graph`，不从固定阶段清单推断。`TaskStatus.stage` 在图执行阶段是 node ID，但生命周期准备阶段可为 `prepare`；重复的同类节点仍是不同实例。

当前串行 GraphExecutor 在节点开始回调 `i/N`，在节点产物验证成功后回调 `(i+1)/N`。注册器将同阶段进度变化记录为 `stage_progress`，数据含 `state`、原始 `progress`；它不是节点内部耗时百分比。前端仅用同任务、有效时间/sequence、同 node 起止边界确认节点完成，缺证据显示未确认。不得从前序位置、日志文字、单个中间音频产物、另一个节点开始或四舍五入进度推断完成。

V2 任务的 `state=completed` 证明实际图节点全部完成；`failed/cancelled/skipped` 与 SSE 流 `done` 不具有该含义。V1 仅显示明确启用的配置阶段，不能把复用或跳过伪装为实际执行成功。任务中心的最小准确性修复不改变调度、模型请求、任务冻结或混音行为。独立任务中心重设计预览不是生产页面替换。


## 6. 任务中心列表、详情与产物归属

任务中心以实际任务/批次记录构建列表，批次成员仅按 item.task_ids 与 current_task_id 的精确 ID 关联，保留先前重试尝试。列表轮询与手动刷新共用一个可失效的轮询链；新的刷新取消旧链对 store 的写入，迟到旧响应不得回退较新的终态。任务详情按选中 ID 隔离，结果/spec 响应及产物本身的 task_id 均须对应当前任务；切换后旧请求不应写入详情。

节点页继续使用冻结图和有效结构化事件证据。产物页区分最终交付、中间片段和未确认归属：V2 最终产物须匹配冻结 graph.outputs 的 node_id/port，speech_take 始终作为中间片段展示，不能仅凭旧 is_primary 回退规则当作最终交付。无法归类的历史记录保留并标注未确认，不隐藏、不猜测成功。取消、显式重试、恢复与音频预览沿原 API 语义，不因浏览、刷新或选择任务而自动执行。
