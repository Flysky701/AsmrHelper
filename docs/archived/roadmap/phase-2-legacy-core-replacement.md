# AsmrHelper Phase 2 后段收尾计划

日期：2026-05-27（2026-07-23 已复核）

## 1. 事实源

本文替代旧的“Legacy Core 替换与主干下沉 V1”计划。

历史计划中曾出现、现在已经失效的判断包括：

- `src/gui/` 仍需保留。
- `src/core/pipeline/` 仍是迁移目标。
- `LegacyPipelineOrchestrator` 仍驱动主路径。
- `script_to_subtitle / subtitle_generator / script_processor` 仍未迁入 `core/subtitles`。

这些判断不再作为当前基准。

当前判断必须以 [当前源码基线](../../roadmap/current-source-baseline.md) 和 [当前架构与文档审计](current-architecture-and-doc-audit-2026-07-23.md) 为准。本计划只定义尚未完成的收尾切片，不能用于推翻已验证的运行状态。

## 2. 当前 Phase 2 状态

当前 Phase 2 已经进入后段收尾。

已完成：

- 旧 GUI 已从源码树移除。
- 旧 `src/core/pipeline/` 已从源码树移除。
- pipeline 主执行路径已迁到 `src/core/orchestration/pipeline/`。
- `core/engines/*` registry/runtime 已成为 pipeline executor 的直接消费对象。
- `core/tasks` 已承接任务模型和轻量状态机。
- `core/subtitles` 已承接脚本、字幕生成、清洗、导出等能力。

仍未完成：

- 部分 app service 仍有旧字段拼装或旧路径引用。
- `ModelManager` 与 `core.translate` 的零调用兼容入口已删除；Qwen3 manager 仍承载实际 Voice 能力，不能按兼容层直接删除。

## 3. 后段目标

Phase 2 后段不再以“删除旧目录”为核心目标。

当前目标是：

1. 让代码先遵守 [数据结构契约 v1](../../contracts/schemas-v1.md)。
2. 让能力参数、敏感设置和 RuntimeBinding 遵守 [Provider 与设置契约 v1](../../contracts/provider-v1.md)。
3. 按 [兼容与迁移说明](../../contracts/compatibility.md) 归一化旧主链路字段。
4. 让 TaskCenter 消费后端显式状态，而不是前端推断阶段。
5. 让 Workbench 进入 `session + task` 主路径。
6. 修掉迁移后残留的旧 import 和旧字段映射。
7. 将兼容入口降级为适配层，不再主导新能力设计。

## 4. 收尾切片

### Slice A：残留旧引用修复（已完成：2026-07-23）

范围：

- `src/app/services/script_subtitle_service.py`
- 相关 tests

目标：

- 将 `src.core.script_to_subtitle` 残留引用改到 `src.core.subtitles.script_to_subtitle`。
- 明确旧路径不存在是当前事实，不再为旧路径保留新依赖。

完成标准：

- 直接加载 script subtitle runtime 不再报 `ModuleNotFoundError`。
- subtitle domain 相关测试继续通过。

完成记录：

- `script_subtitle_service.py` 已改为加载 `src.core.subtitles.script_to_subtitle.ScriptToSubtitlePipeline`。
- 新增真实 runtime 导入路径回归测试；字幕服务与字幕域针对性测试 `38 passed`，当前全量测试 `126 passed`。

### Slice B：基础设施字段统一

范围：

- `src/app/services/capability_descriptor_service.py`
- `src/api/http/schemas/capabilities.py`
- `src/core/resources/model_catalog.py`
- `src/core/resources/model_status.py`
- `src/core/tasks/service.py`
- `src/core/orchestration/pipeline/executor.py`
- `desktop/src/stores/logStore.ts`
- `desktop/src/pages/EnginesResources.tsx`
- `desktop/src/pages/TaskCenter.tsx`

目标：

- 增强 `CapabilityOption`，表达 UI 控件、高级参数、敏感参数和持久化规则。已完成稳定约束字段。
- 引入统一 `RuntimeEvent` 语义，让日志、进度、阶段、模型操作能被 API 和桌面稳定消费。
- 明确 `ModelCatalogEntry`、`CapabilityDescriptor.supported_models`、`ExecutionProfile.model` 的边界。
- 将 provider 私有高级参数统一收进 `provider_options`。

完成标准：

- 新增 provider 高级参数不再扩张 pipeline 顶层字段。
- TaskCenter 能消费结构化日志/阶段事件，而不是从 `message/detail` 推断。
- 模型安装字段不进入 `TaskSpec` 或 `ExecutionProfile`。
- `CapabilityDescriptor` 足以驱动桌面高级参数 UI。

### Slice C：ExecutionProfile 契约落码（已完成：2026-07-23）

范围：

- `src/app/services/pipeline_service.py`
- `src/core/orchestration/pipeline/planner.py`
- `src/app/services/execution_profile_builder.py`
- pipeline API schema / DTO

目标：

- HTTP 仅接受 V1 `input/output/execution_profile`，其中 `execution_profile` 使用 `version + stages`。
- 旧 `pipeline + stages + mix` 仅允许留在内部 DTO 的清理范围，不再作为客户端输入。
- 新增 provider 私有参数进入 `provider_options`，不继续扩张平铺字段。

完成标准：

- `PipelineService.create_pipeline_task_spec()` 能生成主链路数据参数契约定义的新结构。
- `build_execution_plan()` 能消费新结构。
- `POST /pipeline-runs` 是唯一 Pipeline 创建入口，旧入口返回 `404`。

完成记录：

- `PipelineService` 会将 CLI 和 batch 的内部平铺参数归一化为同一套 StageProfile V1，再执行 readiness 和任务创建。
- planner 只消费 StageProfile V1；旧 `pipeline/stages/mix` profile 已拒绝，HTTP 也已删除旧请求 schema、转换 facade 和兼容路由。
- 增加 V1 profile、内部默认参数归一化和旧 profile 拒绝回归测试，并确认旧平铺 HTTP 请求被拒绝。

### Slice D：TaskStatus 字段补齐（已完成：2026-07-23）

范围：

- `src/core/tasks/models.py`
- `src/core/tasks/service.py`
- `src/app/services/task_service.py`
- `src/api/http/schemas/tasks.py`
- `src/api/http/routes/tasks.py`
- pipeline executor progress 回写点

目标：

- 增加 `stage`、`error`、`created_at`、`started_at`、`finished_at`、`artifact_set_id`。
- pipeline 执行阶段回写明确 `stage`。
- 失败时返回结构化错误基础字段。

完成标准：

- TaskCenter 不需要通过 message/detail 猜阶段。
- API 返回字段满足 [主链路契约 v1](../../contracts/mainline-v1.md)。

完成记录：

- `TaskStatus`、Task API 和任务服务已补充 stage、输入资产、时间线、结构化 error 与 artifact_set_id。
- pipeline executor 现在显式回写 `separate/asr/translate/tts/mix/export`；不再需要由后端通过消息文本推断阶段。
- 全量 Python 测试 `126 passed`，桌面 `npm.cmd run build` 通过。

### Slice E：Workbench 主入口迁移

状态：已完成。最终采用一次性 `POST /pipeline-runs`，由后端创建并接管任务；没有把多次 `session + task` 调用暴露给 Workbench。

范围：

- `desktop/src/pages/Workbench.tsx`
- `desktop/src/api/sessions.ts` 或现有 API client
- `desktop/src/api/tasks.ts`
- `desktop/src/stores/taskStore.ts`

目标：

- Workbench 一次提交统一的 `input/output/execution_profile`。
- 只保留 `/pipeline-runs`，不再兼容 `/pipeline/run` 或 `/pipeline/tasks`。

完成标准：

- Workbench 创建任务拿到稳定后端 `task_id`。
- 本地 task id 与 server task id 的关系清晰。

### Slice F：TaskCenter 结果消费对齐

状态：已完成。TaskCenter 使用统一 TaskResult 和 Artifact 声明，不再读取旧 `files/primary_output` 或根据扩展名猜测。

范围：

- `desktop/src/pages/TaskCenter.tsx`
- `desktop/src/api/tasks.ts`
- `desktop/src/api/artifacts.ts` / preview API
- `desktop/src/stores/taskStore.ts`

目标：

- 用后端 `stage` 渲染阶段时间线。
- 用 `TaskResult.artifacts` 渲染产物入口。
- 用 preview API 渲染播放、字幕查看、打开目录。
- 日志继续保留，但只作为排障详情。

完成标准：

- TaskCenter 不再从日志或 message 猜状态。
- 主产物不再靠文件名或本地映射猜测。

### Slice G：兼容层瘦身

范围：

- `pipeline_service`
- `audio_tool_service`
- `script_subtitle_service`
- `translation_service`
- `tts_service`
- `asr_service`
- `ModelManager`（已删除）
- `core.translate`（已删除）

目标：

- app service 主要做校验、DTO 映射、调用 core。
- 保持 `ModelManager` 和 `core.translate` 已删除，测试防止旧入口复活。
- 兼容 route 可以保留，但内部必须尽快转成新 core 对象。

完成标准：

- 关键服务不再大段拼装旧字段。
- 测试明确防止旧路径和旧主入口复活。

## 5. 暂不处理

- 不做跨进程持久化任务队列。
- 不重做音频算法本体。
- 不展开复杂人工审校编辑器。
- 不为已删除旧 GUI 恢复兼容路径。
- 不把归档计划重新当执行入口。

## 6. 当前风险

### 基础设施事件已收束

新旧 execution profile、TaskStatus、CapabilityOption、模型可执行状态和 RuntimeEvent 已经落码。任务生命周期由 TaskStatus 更新生成进程内增量事件，模型安装复用 `model_operation` 事件；事件不作为第二套任务状态，也不承担跨重启恢复。

### 后台执行采用轻量线程模型

Workbench 已走 `/pipeline-runs`，TaskCenter 已消费后端显式阶段。受当前机器性能和个位数线程规模限制，后台任务继续使用进程内轻量线程模型；本阶段不建设独立调度器或持久化执行队列。若未来出现稳定的多任务并发需求，再重新评估。

### 结果与产物语义已收口

终态历史与 Artifact 索引已经持久化；TaskResult、主产物和 Preview 公共字段已按 v1 数据契约统一。旧路径型结果字段只保留在内部执行模型，公共 HTTP 不再暴露。

### 旧路径残留会在运行时炸

P0 的 `script_subtitle_service.py` 残留导入已修复。已删除的 `ModelManager`、`core.translate` 与 core 根包懒加载出口由负向测试保护，避免同类旧入口复发。

## 7. 完成标准

满足以下条件时，Phase 2 后段可以认为完成：

1. `PipelineService` 与 planner 优先消费主链路数据参数契约。
2. `/pipeline-runs` 是唯一 Pipeline 创建入口，只接受 V1 嵌套请求。
3. `CapabilityDescriptor`、`RuntimeEvent`、模型字段和高级参数遵守基础设施契约。
4. `TaskStatus` 足够支撑 TaskCenter，不再依赖前端阶段推断。
5. Workbench 主路径为一次提交 `/pipeline-runs`，由后端创建并接管任务。
6. TaskCenter 主路径为 `tasks + artifacts + preview`。
7. 已删除旧路径没有活跃 import 残留。
8. `ModelManager` 和 `core.translate` 已删除且没有活跃 import 残留。

## 8. 一句话结论

Phase 2 当前不是“继续拆旧目录”，而是：

> 把已经迁出来的新 core、已经接上的桌面端，以及刚收束的主链路契约，合并成同一条稳定可验证的产品主路径。
