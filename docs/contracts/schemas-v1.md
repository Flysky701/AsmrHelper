# 公共数据结构

HTTP 请求与响应以 [Pydantic schema](../../src/api/http/schemas/) 为准，运行实例提供 `/openapi.json`。本页记录关键语义，不复制会随代码变化的完整 schema。

JSON 使用 snake_case，时间为带时区的 ISO 8601，任务 progress 为 0–1。图节点语言当前为 ja、zh、en；具体引擎可用语言另由能力声明限定。图请求严格拒绝未知字段，不接受服务内部快照或凭据作为客户端输入。

## Pipeline 与图

| 结构 | 关键字段 | 来源 |
| --- | --- | --- |
| 单任务请求 | input.path、input.companion_paths、output.directory、execution_profile | [pipeline_runs.py](../../src/api/http/schemas/pipeline_runs.py) |
| V1 配置 | version=1、source_lang、target_lang、skip_existing、stages、可选 workflow | 同上 |
| StageProfile | enabled、provider、model、options、provider_options | 同上 |
| V2 配置 | version=2、graph、bindings | [workflow_graph.py](../../src/api/http/schemas/workflow_graph.py) |
| 图定义 | version=2、nodes、edges、input_slots、outputs | 同上 |
| 素材绑定 | path、language、language_confirmed、audio_path、pair_confirmed、sha256 | 同上 |
| 批次请求 | V1 inputs 或 V2 groups、共同 execution_profile、提交标识及批次选项 | [batch_runs.py](../../src/api/http/schemas/batch_runs.py) |

StageProfile 的 model 可以为 null；显式选项优先，未指定值由对应版本的解析器处理。混音延迟字段 `tts_delay_ms` 单位为毫秒。V1 `skip_existing` 不等于 V2 节点缓存。

V2 节点 ID 在 Windows 文件语义下也须唯一。连线来源是素材槽或节点输出，目标是一个节点输入端口；每个必需输入只能有一个来源。outputs 只能引用节点产物，不能直接引用素材槽。完整语义和兼容限制见[图契约](../guides/workflow-graph-v2.md)。

API Key、SDK 客户端、设备句柄和私有凭据不进入公开执行配置；命名连接按 ID 引用。服务冻结任务所需快照，不能靠修改全局默认改变已经提交的任务。

## 任务与错误

[TaskStatusResponse](../../src/api/http/schemas/tasks.py) 的关键字段为 task_id、task_type、state、stage、progress、message、detail、error，及 created_at、queued_at、started_at、updated_at、finished_at。还包含来源、会话、产物集合、retry_of_task_id 与审阅字段。

state 取 pending、running、completed、failed、cancelled、skipped。响应没有通用的 stages 数组；V2 节点来自冻结图，运行证据来自同任务结构化事件。阶段显示不能把前序位置或四舍五入百分比当作完成证据。

TaskError 使用 code、stage、message、retryable，以及可选 detail/data。message 面向用户，detail 保留脱敏诊断。节点和任务 ID、时间应能定位错误归属；凭据或完整敏感请求不能进入公开 detail/data。

## 产物与结果

[TaskResultResponse](../../src/api/http/schemas/artifacts.py) 返回 task_id、primary_artifact_id、artifacts、warnings。每个产物包含 artifact_id、task_id、type、path、stage、label、primary、preview 和 metadata。

path 是后端提供的本地定位信息，客户端不按文件命名猜测归属。primary 是主产物 ID 的列表表达；V2 交付还须匹配冻结图 outputs 的 node_id/port。speech_take 是中间片段，不能凭旧 primary 标记冒充最终交付。无法归类的历史记录保留并标注未确认。

preview 表示服务声明可预览，实际方式通过 Preview 接口返回。路径型 primary_output/files 等内部执行字段不是公共 TaskResult。

## 就绪检查与模型状态

`POST /api/v1/runtime/check-task-readiness` 接收 task_type、execution_profile、可选 input_path；返回 ready、missing_requirements、issues 和实际检查的 execution_profile。每项 issue 包含 stage、category、provider、model、code、requirement、message、action，见 [resources.py](../../src/api/http/schemas/resources.py)。

检查只针对实际选择的节点或阶段；提交服务负责最终素材及版本校验。配置通过不证明网络鉴权、模型推理或音频质量。模型的 installed 与 executable 分别表达资产状态和运行条件，见 [models.py](../../src/api/http/schemas/models.py)。超时未知不能显示成已就绪。

## RuntimeEvent

事件字段为 sequence、time、level、type、task_id、stage、message、detail、data。sequence 在同任务内递增，客户端使用 after_sequence 增量读取。SSE 的 done 表示事件流结束，须读取携带的任务终态，不能直接视为成功。

事件用于进程内诊断和增量显示，不代替 SQLite 任务事实，也不承诺重启后事件回放。data 不复制完整任务状态或 secret。取消、重试与恢复语义见[任务执行契约](task-execution-v1.md)。
