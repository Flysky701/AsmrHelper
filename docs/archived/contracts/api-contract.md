# [已归档] AsmrHelper 统一 API 契约总表 V1

## 目标

- 将当前已经确认的功能架构，收口成一份统一 API 契约总表。
- 明确每个功能域对外暴露哪些主接口。
- 明确哪些旧接口只是兼容入口，不再主导长期架构。

当前阶段的端到端落地顺序以 [主链路 V1 契约](mainline-v1-contract.md) 为准，字段口径以 [主链路 V1 数据参数契约](mainline-v1-data-parameters.md) 为准。日志事件、模型字段、CapabilityOption、高级参数和 RuntimeBinding 边界以 [基础设施契约 V1](infrastructure-contracts-v1.md) 为准。本文保留系统级接口边界，主链路契约负责把 Workbench、TaskCenter、Artifact、Preview 的最小稳定面串起来。

## 总体原则

### 1. 以功能域分组，不以页面分组

- API 契约按功能域组织。
- 不再按 Workbench、Tools、VoiceLab、Settings 这些页面来倒推接口设计。

### 2. 以主接口和兼容接口区分长期方向

- **主接口**：未来架构应围绕它收口。
- **兼容接口**：当前可保留，但不继续主导能力边界。

### 3. 以任务、资产、能力为中心

- 不再围绕当前平铺表单字段直接扩张 API。
- 新接口优先围绕：
  - `session`
  - `task`
  - `artifact`
  - `CapabilityDescriptor`
  - `ExecutionProfile`
  - `RuntimeEvent`

### 4. 引擎扩展能力不冒充全局主能力

- `/voice/*` 只作为 TTS 扩展能力入口。
- `/translation/*` 只作为 LLM 衍生操作兼容入口。
- 当前单一 ASR 实现不等于最终 ASR 能力边界。

## 功能 1：工作空间与输入管理

### 主接口

- `POST /api/v1/workspaces/resolve`
- `POST /api/v1/inputs/inspect`
- `POST /api/v1/inputs/discover-companions`
- `POST /api/v1/sessions`

### 说明

- 这一组接口负责把路径、输入文件、伴随资源和输出策略整理成标准化会话。
- 后续功能优先消费 `session`，不继续直接围绕裸路径工作。

## 功能 2：单任务音频汉化流水线编排执行器

### 主接口

- `POST /api/v1/pipeline-runs`
- `GET /api/v1/pipeline-runs/{task_id}`
- `GET /api/v1/pipeline-runs/{task_id}/artifacts`
- `POST /api/v1/pipeline-runs/{task_id}/cancel`

### 说明

- 这组接口是单任务流水线执行器视角。
- 长期目标应以 `task_id` 触发或查询执行，而不是继续围绕路径和页面状态驱动。

## 功能 3：统一任务生成与任务队列

### 主接口

- `POST /api/v1/tasks`
- `POST /api/v1/tasks/batch`
- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/result`
- `POST /api/v1/tasks/{task_id}/cancel`
- `POST /api/v1/tasks/{task_id}/retry`
- `GET /api/v1/task-queue`

### 说明

- 所有后台任务最终进入这一组接口管理的统一任务体系。
- 包括：
  - `pipeline`
  - `tool.*`
  - 后续更多后台处理任务

## 功能 4：单步工具执行体系

### 主接口

- `POST /api/v1/tool-runs`
- `GET /api/v1/tool-runs/{task_id}`

### 兼容接口

- `POST /api/v1/tools/separate`
- `POST /api/v1/tools/convert`
- `POST /api/v1/tools/split`
- `POST /api/v1/tools/translate-subtitle`
- `POST /api/v1/tools/volume-preview`
- `POST /api/v1/asr/transcribe`
- `POST /api/v1/tts/synthesize`

### 说明

- 已确认长期主方向是 `tool-runs`。
- 当前 `/tools/*`、`/asr/*`、`/tts/*` 可以保留兼容，但不继续主导整体工具架构。

## 功能 5：模型与运行资源管理

### 主接口

- `GET /api/v1/models`
- `GET /api/v1/models/statuses`
- `GET /api/v1/models/{model_id}/status`
- `POST /api/v1/models/{model_id}/install`
- `POST /api/v1/models/{model_id}/verify`
- `DELETE /api/v1/models/{model_id}`
- `POST /api/v1/models/{model_id}/unload`
- `POST /api/v1/models/unload-all`
- `GET /api/v1/runtime/resources`
- `GET /api/v1/runtime/capabilities`
- `POST /api/v1/runtime/check-task-readiness`

### 说明

- 这组接口负责系统能不能跑、缺什么模型、资源是否 ready。

## 功能 6：配置与提供方接入管理

### 主接口

- `GET /api/v1/settings`
- `PUT /api/v1/settings`
- `POST /api/v1/settings/validate`
- `POST /api/v1/settings/test-provider`
- `GET /api/v1/settings/effective`
- `GET /api/v1/capabilities`
- `GET /api/v1/capabilities/{category}`

### 说明

- 这里是参数定义中心与 provider 接入中心。
- 负责暴露 `CapabilityDescriptor` 和配置层事实。

## 功能 7：字幕与文本资产管理

### 主接口

- `POST /api/v1/subtitles/load`
- `POST /api/v1/subtitles/parse`
- `POST /api/v1/subtitles/normalize`
- `POST /api/v1/subtitles/translate`
- `POST /api/v1/subtitles/bilingualize`
- `POST /api/v1/subtitles/export`
- `POST /api/v1/subtitles/script-to-subtitle`

### 说明

- 这一组接口属于字幕领域本体。
- 即使某些能力同时在工具里出现，其真正业务归属仍在这里。

## 功能 8：结果资产与产物索引管理

### 主接口

- `GET /api/v1/tasks/{task_id}/result`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/artifacts/{artifact_id}`
- `GET /api/v1/artifacts/by-task/{task_id}`

### 说明

- 当前先保留结果资产层独立接口设计。
- 但具体消费方式当前阶段以轻量预览方案为准。

## 功能 9：结果预览、浏览与人工校对

### 当前确认接口

- `GET /api/v1/tasks/{task_id}/preview`
- `POST /api/v1/tasks/{task_id}/review-status`
- `POST /api/v1/tasks/{task_id}/review-note`

### 说明

- 当前阶段只确认轻量预览方案。
- 不继续展开重型编辑器和复杂审校流。

## 功能 10：TTS 引擎管理与扩展能力管理

### 主接口

- `POST /api/v1/tts/synthesize`
- `GET /api/v1/tts/engines`
- `GET /api/v1/tts/engines/{engine_id}`

### 扩展能力兼容接口

- `GET /api/v1/voice/profiles`
- `GET /api/v1/voice/profiles/{profile_id}`
- `POST /api/v1/voice/design`
- `POST /api/v1/voice/clone`
- `POST /api/v1/voice/analyze-segments`
- `POST /api/v1/voice/profiles/{profile_id}/preview`

### 说明

- 已确认 `/voice/*` 只是 TTS 引擎扩展能力入口。
- 不再把它定义成全局稳定一级主能力。

## 功能 11：LLM 能力管理与衍生操作管理

### 主接口

- `GET /api/v1/llm/providers`
- `GET /api/v1/llm/providers/{provider_id}`
- `POST /api/v1/llm/operations/run`

### 兼容接口

- `POST /api/v1/translation/translate`
- `POST /api/v1/tools/translate-subtitle`

### 说明

- 已确认“翻译不是独立引擎层”。
- `/translation/*` 只作为 LLM 衍生操作兼容入口保留。

## 功能 12：ASR 引擎管理与扩展能力管理

### 主接口

- `POST /api/v1/asr/transcribe`
- `GET /api/v1/asr/engines`
- `GET /api/v1/asr/engines/{engine_id}`

### 说明

- 当前 `/api/v1/asr/transcribe` 可以继续作为通用 ASR 主入口。
- 当前单引擎状态不代表最终产品边界，后续应允许多个 ASR 引擎接入。

## 当前已确认的关键架构结论

### 1. 工具系统主入口改为 `tool-runs`

- `/tools/*` 继续兼容
- 但未来主干是 `tool-runs`

### 2. `/voice/*` 不是一级主功能域接口

- 它是功能 10 的 TTS 引擎扩展能力入口

### 3. `/translation/*` 不是一级主功能域接口

- 它是功能 11 的 LLM 衍生操作兼容入口

### 4. 结果消费先走轻量预览方案

- 当前不展开复杂结果系统
- 先以主产物预览、基础试听、轻量人工确认作为主方向

## 推荐后续动作

在这份 API 总表之后，下一步最自然的是继续整理：

1. 中间层 service 映射总表
2. 现有代码到新架构的迁移清单

## 一句话结论

当前 V1 的统一 API 契约已经可以明确为：

> 以 `session / task / artifact / capability / engine` 为主轴组织接口，保留旧接口兼容，但不再让旧页面和旧平铺字段继续主导长期架构。
