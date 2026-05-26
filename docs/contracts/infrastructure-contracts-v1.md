# AsmrHelper 基础设施契约 V1

日期：2026-05-27

## 1. 定位

本文基于当前 `src/desktop` 源码状态，收束日志表示、模型字段、能力参数 schema 与高级参数配置的统一规则。

本文不是旧计划回放。当前事实来自：

- `src/core/tasks/`
- `src/core/resources/`
- `src/core/runtime/`
- `src/core/engines/`
- `src/core/orchestration/pipeline/`
- `src/app/services/capability_descriptor_service.py`
- `src/app/services/execution_profile_builder.py`
- `desktop/src/pages/TaskCenter.tsx`
- `desktop/src/pages/EnginesResources.tsx`

## 2. 当前源码问题

### 2.1 日志和进度有多套表示

当前同时存在：

| 表示方式 | 位置 | 当前用途 | 问题 |
|---|---|---|---|
| `print(...)` | `core/asr`、`core/translate`、`core/subtitles`、`mixer`、`vocal_separator` 等 | 运行过程输出 | 不能被 API、TaskCenter、测试稳定消费 |
| `logging.getLogger(__name__)` | `core/resources`、`core/tasks/dispatcher.py`、部分 app service | 服务诊断 | 没有统一上下文字段 |
| `click.echo(...)` | `src/cli.py` | CLI 展示 | 应只作为展示层，不应成为 runtime 事实源 |
| `TaskStatus.message/detail` | `core/tasks`、`pipeline_service`、前端 task store | 任务状态摘要 | 承载了阶段推断、错误、进度说明等多种职责 |
| 前端本地日志 | `desktop/src/stores/logStore.ts`、TaskCenter | UI 时间线 | 与后端任务事实没有统一事件契约 |

结论：日志、进度、任务状态必须分层。`TaskStatus` 只保存稳定任务状态；运行日志必须用结构化事件表示；CLI 和桌面只是消费这些事件的展示层。

### 2.2 模型字段混在不同语义层

当前 `ModelCatalog` 已经有较完整的资源字段：

```text
family_id
variant_group
variant_tier
dependency_group
runtime_profile
install_modes
required_assets
recommended_assets
preferred_runtime
```

同时 `CapabilityDescriptor` 暴露：

```text
supported_models
default_model
common_option_schema
provider_option_schema
supports
```

`ExecutionProfile` 又使用：

```text
category
provider
model
common_options
provider_options
```

结论：这三者不是同一类字段，不能互相外溢。模型资源字段属于安装与可用性，能力描述字段属于 UI 可选项，执行 profile 字段属于一次任务的可复现配置。

### 2.3 高级参数有入口但缺 schema 约束

当前 TTS / ASR / LLM / separator 已经基本使用 `common_options` 和 `provider_options`，但仍有问题：

- `CapabilityOption` 只有 `name/type/required/default/description`，不足以驱动 UI 控件和参数校验。
- `/pipeline/run` 仍有 `engine_params`、`tts_voice`、`voice_profile_id` 等兼容字段。
- `ExecutionProfileBuilder` 只构建单 category profile，还没有统一构建主链路 aggregate profile。
- provider 私有参数的持久化、安全、是否高级参数、UI 控件类型尚未显式声明。

## 3. 基础分层

以后基础设施字段按五层分开。

| 层 | 对象 | 负责什么 | 不负责什么 |
|---|---|---|---|
| 资源目录层 | `ModelCatalogEntry` | 模型安装、依赖、文件、运行环境要求 | 一次任务怎么跑 |
| 能力描述层 | `CapabilityDescriptor` | provider 能力、可选模型、参数 schema、UI 控件元信息 | 本地路径解析、API key、任务状态 |
| 执行配置层 | `ExecutionProfile` | 一次任务选择的 provider/model/options | secret、runtime client、资源安装细节 |
| 运行绑定层 | `RuntimeBinding` | 执行时注入的路径、client、secret、device、resolved model dir | 持久化任务参数 |
| 运行事件层 | `RuntimeEvent` | 日志、进度、警告、错误、阶段事件 | 替代 TaskStatus 的最终状态 |

## 4. RuntimeEvent 契约

`RuntimeEvent` 是运行日志、阶段进度和诊断信息的统一事件。

```json
{
  "event_id": "evt-001",
  "timestamp": "2026-05-27T12:00:00+08:00",
  "level": "info",
  "event_type": "progress",
  "source": "core.orchestration.pipeline.executor",
  "task_id": "pipeline-001",
  "session_id": "session-001",
  "task_type": "pipeline",
  "stage": "asr",
  "progress": 0.42,
  "message": "语音识别中",
  "detail": "",
  "code": "",
  "category": "asr",
  "provider": "faster_whisper",
  "model": "faster-whisper-base",
  "artifact_id": "",
  "metadata": {}
}
```

### 4.1 字段

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `event_id` | string | 是 | 后端生成，可本进程内唯一 |
| `timestamp` | string | 是 | ISO 8601，带时区 |
| `level` | enum | 是 | `debug` / `info` / `warning` / `error` |
| `event_type` | enum | 是 | 见下表 |
| `source` | string | 是 | Python logger name 或 service id |
| `task_id` | string | 否 | 有任务上下文时必须填 |
| `session_id` | string | 否 | 有 session 上下文时必须填 |
| `task_type` | string | 否 | 与 `TaskSpec.task_type` 一致 |
| `stage` | string \| null | 是 | 无阶段时为 `null` |
| `progress` | number \| null | 是 | `0.0-1.0`，非进度事件为 `null` |
| `message` | string | 是 | 用户可读摘要 |
| `detail` | string | 是 | 排障详情，可为空 |
| `code` | string | 是 | 机器可读代码，可为空 |
| `category` | string | 否 | `tts/asr/llm/separator/mix/export/model/task` |
| `provider` | string | 否 | provider id |
| `model` | string | 否 | 执行 profile 里的 model id |
| `artifact_id` | string | 否 | 事件关联产物 |
| `metadata` | object | 是 | 非核心扩展信息，不放 secret |

### 4.2 event_type

| event_type | 用途 |
|---|---|
| `log` | 普通运行日志 |
| `progress` | 可映射到任务进度的事件 |
| `stage_started` | 阶段开始 |
| `stage_completed` | 阶段完成 |
| `stage_skipped` | 阶段跳过 |
| `warning` | 非阻塞问题 |
| `error` | 阻塞错误 |
| `artifact_created` | 新产物生成 |
| `model_operation` | 模型安装、校验、卸载、加载 |
| `capability_validation` | 参数校验或能力选择结果 |

### 4.3 与 TaskStatus 的关系

`TaskStatus` 是当前任务快照；`RuntimeEvent` 是过程时间线。

规则：

- `TaskStatus.stage` 只能来自明确阶段事件或 executor 显式写入。
- `TaskStatus.progress` 只能来自 `progress` 事件或 task service 显式更新。
- `TaskStatus.message/detail` 保存最后一条适合展示的摘要，不保存完整日志。
- TaskCenter 的时间线应消费 `RuntimeEvent` 或后端聚合后的 event list，不再解析 `message/detail`。

## 5. 日志落地规则

### 5.1 Python 侧

规则：

- core 和 app service 新代码统一使用 `logging.getLogger(__name__)`。
- `print(...)` 只允许保留在一次性脚本或临时调试中，不作为新 runtime 代码输出。
- 长任务内部优先发 `RuntimeEvent`，再由 adapter 同步更新 `TaskStatus`。
- `click.echo(...)` 只用于 CLI 最终展示，不参与任务状态或桌面日志事实。

推荐过渡方式：

```text
legacy print -> logger.info/warning/error -> RuntimeEvent adapter -> TaskStatus + desktop event stream
```

### 5.2 前端侧

规则：

- `desktop/src/stores/logStore.ts` 应逐步改为保存 `RuntimeEvent` 兼容形态。
- TaskCenter 不再从 `message/detail/progress` 推断阶段。
- EnginesResources 的安装进度应消费 `model_operation` 或 `TaskStatus` 显式字段。
- UI 可以生成本地日志，但必须标记 `source: "desktop.*"`，不能伪装成后端运行事实。

## 6. 模型字段契约

### 6.1 ModelCatalogEntry

`ModelCatalogEntry` 是安装资源事实源，字段只描述资源和运行环境。

允许字段：

| 字段组 | 字段 |
|---|---|
| 身份 | `id`、`kind`、`category`、`display_name`、`description` |
| provider 归属 | `provider`、`engine` |
| 安装位置 | `install_root`、`install_path`、`required_files`、`required_dirs` |
| 变体分组 | `family_id`、`variant_group`、`variant_tier`、`is_primary_variant` |
| 依赖 | `dependency_group`、`required_python_extras`、`required_runtime_packages`、`recommended_runtime_packages` |
| 运行环境 | `runtime_profile`、`preferred_runtime`、`supported_os`、`requires_gpu`、`min_cuda` |
| 安装策略 | `install_modes`、`default_install_mode`、`download_sources`、`post_install_checks` |
| 伴随资产 | `required_assets`、`recommended_assets`、`optional_assets` |

禁止外溢：

- 不把 `family_id`、`variant_group`、`runtime_profile` 放入 `ExecutionProfile`。
- 不把本地 `install_path` 放入 `TaskSpec`。
- 不把 `api_key_config` 展示为任务参数。

### 6.2 ModelRef

需要在能力描述和执行配置之间引用模型时，使用轻量 `ModelRef` 语义。

```json
{
  "category": "asr",
  "provider": "faster_whisper",
  "model": "faster-whisper-base",
  "resource_id": "faster-whisper-base"
}
```

规则：

- `model` 是用户选择和执行 profile 保存的值。
- `resource_id` 是可选资源目录 id，用于安装状态查询。
- 本地路径由 `RuntimeBinding` 根据 `resource_id` 解析，不写入 `ExecutionProfile`。
- 云端模型可以没有 `resource_id`。

### 6.3 CapabilityDescriptor 中的模型字段

`CapabilityDescriptor.supported_models` 是 UI 和 profile builder 的候选值。

规则：

- `default_model` 必须在 `supported_models` 内，除非 `supported_models` 为空。
- 如果候选模型需要本地安装，候选值应能映射到 `ModelCatalogEntry.id` 或明确的 `resource_id`。
- `supports` 可以包含能力元数据，但不应用来塞 provider 参数默认值。

## 7. CapabilityOption 契约扩展

当前源码已有：

```text
name
type
required
default
description
```

目标扩展为：

| 字段 | 类型 | 必填 | 用途 |
|---|---|---|---|
| `name` | string | 是 | 参数名，snake_case |
| `type` | enum | 是 | `string/number/integer/boolean/array/object` |
| `required` | boolean | 是 | 是否必填 |
| `default` | any | 否 | 默认值 |
| `description` | string | 是 | 人类可读说明 |
| `label` | string | 否 | UI 短标签 |
| `help_text` | string | 否 | UI 帮助说明 |
| `enum` | array | 否 | 离散可选值 |
| `min` | number | 否 | 数字下限 |
| `max` | number | 否 | 数字上限 |
| `step` | number | 否 | 数字步进 |
| `ui_control` | enum | 否 | `input/select/slider/toggle/file/path/textarea/json` |
| `advanced` | boolean | 是 | 是否高级参数 |
| `secret` | boolean | 是 | 是否敏感 |
| `persistable` | boolean | 是 | 是否允许进入 `ExecutionProfile` |
| `runtime_only` | boolean | 是 | 是否只能进入 `RuntimeBinding` |

默认规则：

- 未声明 `advanced` 时视为 `false`。
- 未声明 `secret` 时视为 `false`。
- 未声明 `persistable` 时视为 `true`。
- `secret=true` 时必须 `persistable=false`。
- `runtime_only=true` 时不得进入 `ExecutionProfile`。

## 8. 高级参数规则

### 8.1 common_options

`common_options` 只放跨 provider 稳定语义。

示例：

| category | common_options |
|---|---|
| `tts` | `voice`、`speed`、`language` |
| `asr` | `language` |
| `llm` | `temperature`、`max_tokens` |
| `separator` | 当前可为空 |
| `mix` | `original_volume`、`tts_volume_ratio`、`tts_delay` |
| `export` | `subtitle_format`、`audio_format` |

### 8.2 provider_options

`provider_options` 只放 provider 私有参数。

规则：

- 新增 provider 参数必须先进入 `CapabilityDescriptor.provider_option_schema`。
- UI 根据 schema 渲染高级参数，不硬编码 provider 私有字段。
- `/pipeline/run.engine_params` 只作为兼容入口，最终映射到 `profiles.{stage}.provider_options`。
- `voice_profile_id` 属于 TTS provider 私有参数，进入 `profiles.tts.provider_options.voice_profile_id`。

### 8.3 RuntimeBinding

以下字段不得进入 `ExecutionProfile`，只能在执行时通过 `RuntimeBinding` 或 settings 注入：

| 类型 | 示例 |
|---|---|
| secret | API key、token |
| client | OpenAI client、HTTP session、model runtime instance |
| 本地解析路径 | resolved model dir、cache dir、temp dir |
| 设备绑定 | CUDA device、GPU lock、loaded model handle |
| 安装策略 | mirror、force install、dependency install flags |

## 9. TTS 参数收束

当前 TTS provider：

```text
edge
qwen3
kokoro
voxcpm2
```

规则：

- `/tts/synthesize.engine` 是兼容字段，内部语义为 `provider`。
- `/tts/synthesize.voice` 和 `speed` 是便捷字段，只映射到 `common_options`。
- provider 私有参数只能走 `provider_options`。
- VoxCPM2 的 `cfg_value/inference_timesteps/device_map/reference_wav_path/prompt_wav_path/prompt_text` 必须由 schema 声明后进入 `provider_options`。
- Qwen3 的 `voice_profile_id/emotion/temperature` 必须由 schema 声明后进入 `provider_options`。

## 10. API 和桌面约束

### 10.1 API

后端 API schema 需要逐步补齐：

- `CapabilityOptionResponse` 增加 `label/help_text/enum/min/max/step/ui_control/advanced/secret/persistable/runtime_only`。
- `CapabilityDescriptorResponse.supports` 类型使用 `dict[str, Any]`，因为当前源码已有数字型能力元数据。
- `TaskStatusResponse` 增加 `stage/error/timestamps/artifact_set_id`。
- 新任务创建优先接收 `ExecutionProfile` aggregate 结构。

### 10.2 Desktop

桌面端约束：

- 参数面板从 `CapabilityDescriptor` 渲染 provider 参数。
- 高级参数默认折叠，但保存时进入 `common_options/provider_options`。
- TaskCenter 阶段从 `TaskStatus.stage` 或 `RuntimeEvent.stage` 来。
- 日志详情从 `RuntimeEvent` 来。
- 模型页继续消费 `ModelSummaryResponse` 和 `ModelStatusResponse`，不把模型安装字段带进任务参数。

## 11. 迁移顺序

1. 扩展 `CapabilityOptionResponse` 和 `CapabilityDescriptorService._option()`，让 schema 能表达 UI 控件、高级参数和持久化规则。
2. 新增 `RuntimeEvent` core model 和最小 event sink，先不要求持久化。
3. 让 pipeline executor 的 `progress_callback` 从纯 message 过渡到结构化 event，adapter 同步更新 `TaskStatus`。
4. 将高频 `print(...)` 模块逐步改为 logger + event emitter，优先处理 pipeline 主链路会调用的 ASR、TTS、LLM、separator、mixer。
5. 将 `/pipeline/run.engine_params`、`voice_profile_id` 等兼容字段统一映射进 `ExecutionProfile.profiles.*.provider_options`。
6. Desktop 高级参数面板改为消费 capability schema，不再为每个 provider 手写顶层字段。
7. TaskCenter 改为消费 `TaskStatus + RuntimeEvent + ArtifactSet`，完全移除阶段猜测。

## 12. 验收标准

基础设施契约落地完成，当且仅当：

- 新增 provider 高级参数不需要扩展 pipeline 顶层字段。
- `CapabilityDescriptor` 足够驱动桌面参数 UI。
- `ExecutionProfile` 不包含 secret、本地解析路径、安装策略或 runtime client。
- TaskCenter 的阶段和日志不再依赖 `message/detail` 推断。
- pipeline 主链路不再直接 `print(...)` 输出运行事实。
- 模型安装字段只出现在资源/模型接口，不污染任务参数。
- TTS、ASR、LLM、separator 的 provider 私有参数都通过 `provider_options` 传递。
