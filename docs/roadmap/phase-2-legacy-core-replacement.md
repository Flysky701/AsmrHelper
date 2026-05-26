# AsmrHelper Phase 2 后段收尾计划

日期：2026-05-27

## 1. 事实源

本文替代旧的“Legacy Core 替换与主干下沉 V1”计划。

旧计划中的很多判断已经过时，例如：

- `src/gui/` 仍需保留。
- `src/core/pipeline/` 仍是迁移目标。
- `LegacyPipelineOrchestrator` 仍驱动主路径。
- `script_to_subtitle / subtitle_generator / script_processor` 仍未迁入 `core/subtitles`。

这些判断不再作为当前基准。

当前判断必须以 [当前源码基线](current-source-baseline.md) 为准。

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

- 主链路数据参数契约尚未完全落码。
- `TaskStatus` 尚未提供足够明确的阶段、时间戳、错误和 artifact 关联字段。
- 桌面端仍通过兼容 `/pipeline/run` 创建主链路任务。
- 部分 app service 仍有旧字段拼装或旧路径引用。
- `ModelManager`、`core.translate`、Qwen3 manager 等兼容层仍需继续收束。

## 3. 后段目标

Phase 2 后段不再以“删除旧目录”为核心目标。

当前目标是：

1. 让代码先遵守 [字段契约约束 V1](../contracts/field-contracts-v1.md)。
2. 让日志事件、模型字段、高级参数和 RuntimeBinding 遵守 [基础设施契约 V1](../contracts/infrastructure-contracts-v1.md)。
3. 让代码消费 [主链路 V1 数据参数契约](../contracts/mainline-v1-data-parameters.md)。
4. 让 TaskCenter 消费后端显式状态，而不是前端推断阶段。
5. 让 Workbench 进入 `session + task` 主路径。
6. 修掉迁移后残留的旧 import 和旧字段映射。
7. 将兼容入口降级为适配层，不再主导新能力设计。

## 4. 收尾切片

### Slice A：残留旧引用修复

范围：

- `src/app/services/script_subtitle_service.py`
- 相关 tests

目标：

- 将 `src.core.script_to_subtitle` 残留引用改到 `src.core.subtitles.script_to_subtitle`。
- 明确旧路径不存在是当前事实，不再为旧路径保留新依赖。

完成标准：

- 直接加载 script subtitle runtime 不再报 `ModuleNotFoundError`。
- subtitle domain 相关测试继续通过。

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

- 增强 `CapabilityOption`，表达 UI 控件、高级参数、敏感参数和持久化规则。
- 引入统一 `RuntimeEvent` 语义，让日志、进度、阶段、模型操作能被 API 和桌面稳定消费。
- 明确 `ModelCatalogEntry`、`CapabilityDescriptor.supported_models`、`ExecutionProfile.model` 的边界。
- 将 provider 私有高级参数统一收进 `provider_options`。

完成标准：

- 新增 provider 高级参数不再扩张 pipeline 顶层字段。
- TaskCenter 能消费结构化日志/阶段事件，而不是从 `message/detail` 推断。
- 模型安装字段不进入 `TaskSpec` 或 `ExecutionProfile`。
- `CapabilityDescriptor` 足以驱动桌面高级参数 UI。

### Slice C：ExecutionProfile 契约落码

范围：

- `src/app/services/pipeline_service.py`
- `src/core/orchestration/pipeline/planner.py`
- `src/app/services/execution_profile_builder.py`
- pipeline API schema / DTO

目标：

- 新结构优先：`profile_version + stages + profiles`。
- 旧结构兼容：`pipeline + stages + mix` 在过渡期仍可执行。
- 新增 provider 私有参数进入 `provider_options`，不继续扩张平铺字段。

完成标准：

- `PipelineService.create_pipeline_task_spec()` 能生成主链路数据参数契约定义的新结构。
- `build_execution_plan()` 能消费新结构。
- 旧 `/pipeline/run` 仍可通过适配层工作。

### Slice D：TaskStatus 字段补齐

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
- API 返回字段满足 [主链路 V1 契约](../contracts/mainline-v1-contract.md)。

### Slice E：Workbench 主入口迁移

范围：

- `desktop/src/pages/Workbench.tsx`
- `desktop/src/api/sessions.ts` 或现有 API client
- `desktop/src/api/tasks.ts`
- `desktop/src/stores/taskStore.ts`

目标：

- 创建任务时先建 session，再建 task。
- `/pipeline/run` 保留为兼容入口，但不再是 Workbench 主路径。

完成标准：

- Workbench 创建任务拿到稳定后端 `task_id`。
- 本地 task id 与 server task id 的关系清晰。

### Slice F：TaskCenter 结果消费对齐

范围：

- `desktop/src/pages/TaskCenter.tsx`
- `desktop/src/api/tasks.ts`
- `desktop/src/api/artifacts.ts` / preview API
- `desktop/src/stores/taskStore.ts`

目标：

- 用后端 `stage` 渲染阶段时间线。
- 用 `ArtifactSet` 渲染产物入口。
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
- `ModelManager`
- `core.translate`

目标：

- app service 主要做校验、DTO 映射、调用 core。
- 新代码不再新增对 `ModelManager` 和 `core.translate` 的直接依赖。
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

### 契约与代码双轨

DOCS 已经收束了主链路契约，但代码仍有旧 execution profile 结构。如果不尽快落码，后续 UI 和后端会再次互相猜字段。

### 桌面端可用但主路径未正名

Workbench 当前可跑，但仍走 `/pipeline/run`。这会让兼容入口继续主导参数结构。

### TaskCenter 阶段展示仍可能误判

当前阶段展示仍存在前端推断。只要后端不提供显式 `stage`，TaskCenter 就无法成为可靠任务驾驶舱。

### 旧路径残留会在运行时炸

例如 `script_subtitle_service.py` 仍指向已删除旧路径。这类问题不会被 `compileall` 覆盖所有运行分支，必须补针对性测试。

## 7. 完成标准

满足以下条件时，Phase 2 后段可以认为完成：

1. `PipelineService` 与 planner 优先消费主链路数据参数契约。
2. `/pipeline/run` 只是兼容适配入口，不再定义新字段。
3. `CapabilityDescriptor`、`RuntimeEvent`、模型字段和高级参数遵守基础设施契约。
4. `TaskStatus` 足够支撑 TaskCenter，不再依赖前端阶段推断。
5. Workbench 主路径为 `session + task`。
6. TaskCenter 主路径为 `tasks + artifacts + preview`。
7. 已删除旧路径没有活跃 import 残留。
8. `ModelManager` 和 `core.translate` 不再是新服务的默认依赖入口。

## 8. 一句话结论

Phase 2 当前不是“继续拆旧目录”，而是：

> 把已经迁出来的新 core、已经接上的桌面端，以及刚收束的主链路契约，合并成同一条稳定可验证的产品主路径。
