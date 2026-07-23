# [已归档] AsmrHelper 字段契约约束 V1

日期：2026-05-27

## 1. 契约目的

本文基于当前 Git 与 `src/desktop` 源码状态重新定义字段契约，不再从旧 Phase 2 文档倒推字段。

本文覆盖：

- Task 字段。
- Service / executor 边界字段。
- CapabilityDescriptor 字段。
- ExecutionProfile 字段。
- TTS 字段。
- Artifact / Preview 字段。
- 前端字段消费约束。

当前源码事实见 [当前源码基线](../../roadmap/current-source-baseline.md)。
日志事件、模型资源字段、CapabilityOption 扩展、高级参数和 RuntimeBinding 的横向规则见 [基础设施契约 V1](infrastructure-contracts-v1.md)。

## 2. 总体规则

### 2.1 命名

| 层 | 规则 |
|---|---|
| Python / API JSON | 使用 `snake_case` |
| TypeScript API type | 与 API JSON 保持 `snake_case` |
| React component 内部局部变量 | 可使用 `camelCase`，但不得改变 API 字段语义 |
| provider id | 使用小写 snake 或短横线既有 id，新增优先 snake，例如 `faster_whisper` |
| task type | 使用点分命名表达子类型，例如 `tool.tts` |

### 2.2 进度

当前后端 `TaskStatusResponse.progress` 是 `0.0-1.0` 浮点数。

规则：

- 后端、API、TaskStore 的事实进度统一为 `0.0-1.0`。
- 前端展示百分比时乘以 `100`。
- 不再新增 `0-100` 的后端进度字段。
- 如果兼容旧前端局部状态中存在 `0-100`，必须在适配层转换，不得进入 API 契约。

### 2.3 时间

时间字段统一为 ISO 8601 字符串，带时区。

```text
2026-05-27T12:00:00+08:00
```

规则：

- 未发生的时间使用 `null`。
- 不使用空字符串表示未知时间。
- 前端可转换为 number timestamp，但 API 不输出 number timestamp。

### 2.4 路径

当前桌面应用处理本地文件，路径允许是本地绝对路径。

规则：

- API 字段使用 UTF-8 字符串。
- Workbench 不拼接最终输出文件名。
- Artifact 是产物路径事实源。
- TaskCenter 不通过文件名猜测主产物。

### 2.5 错误

所有任务级失败应逐步收束为结构化错误。

```json
{
  "code": "ASR_MODEL_NOT_READY",
  "stage": "asr",
  "message": "ASR 模型不可用",
  "recoverable": true,
  "hint": "请在引擎与资源页面检查模型状态",
  "detail": "optional debug detail"
}
```

规则：

- `message` 给用户看。
- `detail` 给排障看。
- `code` 给前端和测试判断。
- `recoverable` 决定是否突出重试入口。
- 不把 Python traceback 直接放进普通用户消息。

## 3. TaskSpec 契约

当前源码已有：

```text
src/core/tasks/models.py
src/api/http/schemas/tasks.py
```

目标 `TaskSpec` 字段如下。

| 字段 | 类型 | 必填 | 当前状态 | 约束 |
|---|---|---|---|---|
| `task_id` | string | 是 | 已有 | 后端生成，格式建议 `{task_type}-{counter}` 或未来稳定 id |
| `task_type` | string | 是 | 已有 | `pipeline` / `tool.*` / `model.install` 等 |
| `task_source` | string | 是 | 已有 | `desktop.workbench` / `desktop.task_center` / `api` / `compat.pipeline_run` |
| `session_id` | string | 是 | 已有 | 主链路必须有；兼容入口由适配层创建 session |
| `input_asset_id` | string | 是 | 已有 | 主输入资产 id；无输入任务可为空 |
| `companion_asset_ids` | string[] | 是 | 已有 | 可为空数组 |
| `execution_profile` | object | 是 | 已有 | 必须符合本文第 7 节 |
| `priority` | number | 否 | 已有 | 默认 `0`，数字越大优先级越高 |
| `dedupe_key` | string | 否 | 已有 | 由后端生成或前端显式传入 |
| `created_at` | string | 是 | 已有 | ISO 8601 |
| `tags` | string[] | 否 | 待补 | 可选扩展，不参与核心逻辑 |
| `metadata` | object | 否 | 待补 | 非关键展示信息，不得放敏感字段 |

### task_type 枚举建议

| task_type | 用途 |
|---|---|
| `pipeline` | 主链路音频汉化任务 |
| `tool.separate` | 单步人声分离 |
| `tool.asr` | 单步 ASR |
| `tool.translate_subtitle` | 单步字幕翻译 |
| `tool.tts` | 单步 TTS |
| `tool.split` | 单步切分 |
| `tool.convert` | 单步格式转换 |
| `tool.script_to_subtitle` | 脚本转字幕 |
| `model.install` | 模型安装 |
| `model.verify` | 模型校验 |

兼容旧前端的 `script-to-vtt`、`translate-subtitle` 等 UI 名称不得直接成为新 `task_type`。

## 4. TaskStatus 契约

当前 `TaskStatus` 字段偏轻量，需要扩展。

目标字段如下。

| 字段 | 类型 | 必填 | 当前状态 | 约束 |
|---|---|---|---|---|
| `task_id` | string | 是 | 已有 | 与 `TaskSpec.task_id` 一致 |
| `state` | enum | 是 | 已有 | 见下方枚举 |
| `stage` | string \| null | 是 | 待补 | 当前执行阶段，空闲或未知为 `null` |
| `progress` | number | 是 | 已有 | `0.0-1.0` |
| `message` | string | 是 | 已有 | 用户可读摘要 |
| `detail` | string | 是 | 已有 | 排障详情，可为空 |
| `task_type` | string | 是 | 已有 | 与 spec 一致 |
| `task_source` | string | 是 | 已有 | 与 spec 一致 |
| `session_id` | string | 是 | 已有 | 与 spec 一致 |
| `input_asset_id` | string | 否 | 待补 | 便于前端无需再查 spec |
| `created_at` | string | 是 | 待补 | 从 spec 带出 |
| `queued_at` | string \| null | 否 | 待补 | 进入队列时间 |
| `started_at` | string \| null | 是 | 待补 | 开始执行时间 |
| `updated_at` | string | 是 | 待补 | 最近状态更新时间 |
| `finished_at` | string \| null | 是 | 待补 | 终态时间 |
| `error` | object \| null | 是 | 待补 | 结构化错误 |
| `artifact_set_id` | string \| null | 是 | 待补 | 结果产物集合 id |
| `review_state` | enum | 是 | 已有 | 见下方枚举 |
| `review_note` | string | 是 | 已有 | 人工备注 |

### state

| state | 说明 | 进度规则 |
|---|---|---|
| `pending` | 已创建，等待执行 | 通常 `0.0` |
| `running` | 正在执行 | `0.0-1.0` |
| `completed` | 成功完成 | 必须 `1.0` |
| `failed` | 执行失败 | 保留最后进度 |
| `cancelled` | 用户取消 | 保留最后进度 |
| `skipped` | 因策略跳过 | 可为 `1.0` |

### stage

pipeline 标准阶段：

| stage | 说明 |
|---|---|
| `prepare` | 准备输入和输出目录 |
| `separate` | 人声分离 |
| `asr` | 语音识别 |
| `translate` | 字幕翻译 |
| `tts` | 语音合成 |
| `mix` | 混音输出 |
| `export` | 导出产物和预览 |

工具任务阶段可使用：

```text
prepare
execute
export
```

前端不得再从 `message/detail` 推断阶段。

### review_state

| review_state | 说明 |
|---|---|
| `` | 未设置 |
| `accepted` | 已接受 |
| `needs_review` | 需要复核 |
| `needs_rework` | 需要返工 |

## 5. Service 边界字段

Service 层不应继续直接暴露页面字段，而应围绕领域对象工作。

### 5.1 Service 输入上下文

pipeline / tool executor 的内部输入上下文统一为：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `task_id` | string | 是 | 当前任务 |
| `task_type` | string | 是 | 执行器分发依据 |
| `session_id` | string | 是 | 输入和输出上下文 |
| `input_asset_id` | string | 是 | 主输入 |
| `companion_asset_ids` | string[] | 是 | 伴随资源 |
| `execution_profile` | object | 是 | 冻结后的执行配置 |
| `runtime_binding` | object \| null | 是 | 执行时注入，不持久化 |
| `cancel_token` | object \| null | 否 | 协作取消 |

兼容 `PipelineRequest(input_path, ...)` 只能存在于 route 或 facade 适配层。

### 5.2 StageResult

executor 每个阶段应返回或回写标准阶段结果。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stage` | string | 是 | 阶段名 |
| `state` | enum | 是 | `completed` / `failed` / `skipped` |
| `started_at` | string | 否 | 阶段开始 |
| `finished_at` | string | 否 | 阶段结束 |
| `duration_ms` | number | 否 | 阶段耗时 |
| `progress_start` | number | 否 | 阶段起始进度 |
| `progress_end` | number | 否 | 阶段结束进度 |
| `artifact_ids` | string[] | 是 | 阶段产物 |
| `warnings` | string[] | 是 | 非阻塞警告 |
| `error` | object \| null | 是 | 结构化错误 |
| `metadata` | object | 是 | 阶段补充信息 |

### 5.3 ServiceResult

app service 返回给 route 的结果对象应逐步统一：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `success` | boolean | 是 | 是否成功 |
| `task_id` | string | 否 | 有任务时必须返回 |
| `task` | TaskStatus | 否 | 当前任务状态 |
| `artifact_set` | ArtifactSet | 否 | 结果产物 |
| `stage_results` | StageResult[] | 是 | 阶段结果 |
| `warnings` | string[] | 是 | 警告 |
| `error` | object \| null | 是 | 结构化错误 |
| `duration_ms` | number | 否 | 总耗时 |

旧 `PipelineResult.steps` 可作为兼容字段保留，但不作为新 UI 事实源。

## 6. CapabilityDescriptor 契约

当前源码已有 `CapabilityDescriptorService`，字段继续沿用，但需要强化约束。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `category` | enum | 是 | `tts` / `asr` / `llm` / `separator` / `mix` / `export` |
| `provider` | string | 是 | provider id |
| `display_name` | string | 是 | UI 展示名 |
| `kind` | enum | 是 | `local` / `cloud` / `builtin` |
| `supported_models` | string[] | 是 | 可为空但必须存在 |
| `default_model` | string | 是 | 必须在 supported_models 内，除非 supported_models 为空 |
| `common_option_schema` | CapabilityOption[] | 是 | 公共参数 |
| `provider_option_schema` | CapabilityOption[] | 是 | provider 私有参数 |
| `supports` | object | 是 | 能力布尔或能力元数据 |

### CapabilityOption

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `name` | string | 是 | snake_case |
| `type` | enum | 是 | `string` / `number` / `integer` / `boolean` / `array` / `object` |
| `required` | boolean | 是 | 默认 `false` |
| `default` | any | 否 | 必须符合 `type` |
| `description` | string | 是 | 可为空 |
| `enum` | array | 否 | 可选，UI 可渲染 select |
| `min` | number | 否 | 数字下限 |
| `max` | number | 否 | 数字上限 |

当前 `CapabilityOptionResponse` 还缺 `enum/min/max`，也缺少 UI 控件、高级参数、敏感参数和持久化规则。扩展字段以 [基础设施契约 V1](infrastructure-contracts-v1.md) 为准。

## 7. ExecutionProfile 契约

主链路统一使用：

```json
{
  "profile_version": "mainline.v1",
  "source_lang": "ja",
  "target_lang": "zh-CN",
  "preset_id": "default_ja_to_zh",
  "stages": {
    "separate": true,
    "asr": true,
    "translate": true,
    "tts": true,
    "mix": true,
    "export": true
  },
  "profiles": {
    "tts": {
      "category": "tts",
      "provider": "edge",
      "model": "default",
      "common_options": {
        "voice": "zh-CN-XiaoxiaoNeural",
        "speed": 1.0
      },
      "provider_options": {}
    }
  },
  "skip_existing": false
}
```

约束：

- `profile_version` 必须存在。
- `stages` 只表达启停，不塞 provider 参数。
- `profiles.{stage}` 使用统一 profile 结构。
- provider 私有参数只能进入 `provider_options`。
- API key、base URL、本地模型解析路径、runtime client 不得进入 `ExecutionProfile`。

### profile key

| key | category | 说明 |
|---|---|---|
| `separator` | `separator` | 人声分离 |
| `asr` | `asr` | 语音识别 |
| `translation` | `llm` | 翻译阶段 |
| `tts` | `tts` | 语音合成 |
| `mix` | `mix` | 混音 |
| `export` | `export` | 导出 |

当前代码中仍有旧结构：

```text
execution_profile.pipeline
execution_profile.stages.{asr,llm,tts}
execution_profile.mix
```

迁移规则：

- planner 过渡期同时接受旧结构和新结构。
- `PipelineService.create_pipeline_task_spec()` 应优先生成新结构。
- 旧 `/pipeline/run` 字段只在适配层映射。

## 8. TTS 字段契约

当前 TTS provider：

```text
edge
qwen3
kokoro
voxcpm2
```

### 8.1 TTS Profile

```json
{
  "category": "tts",
  "provider": "edge",
  "model": "default",
  "common_options": {
    "voice": "zh-CN-XiaoxiaoNeural",
    "speed": 1.0,
    "language": "zh-CN"
  },
  "provider_options": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `category` | string | 是 | 固定 `tts` |
| `provider` | string | 是 | `edge` / `qwen3` / `kokoro` / `voxcpm2` |
| `model` | string | 是 | 默认 `default` |
| `common_options.voice` | string | 否 | 音色、speaker 或 voice mode |
| `common_options.speed` | number | 否 | 默认 `1.0` |
| `common_options.language` | string | 否 | 默认顶层 `target_lang` |
| `provider_options` | object | 是 | provider 私有参数 |

### 8.2 provider_options

#### edge

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| 无 | - | - | 当前只使用公共 `voice/speed` |

#### qwen3

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `voice_profile_id` | string | 无 | 自定义音色 profile |
| `emotion` | string | 无 | 情绪提示 |
| `temperature` | number | 无 | 采样温度 |

#### kokoro

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `lang_code` | string | 无 | Kokoro 语言码 |
| `repo_id` | string | 无 | 自定义 repo |
| `split_pattern` | string | `\\n+` | 文本切分规则 |
| `sample_rate` | integer | `24000` | 输出采样率 |

#### voxcpm2

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `model_dir` | string | 无 | 本地模型目录或 repo id |
| `cfg_value` | number | `2.0` | CFG scale |
| `inference_timesteps` | integer | `10` | 推理步数 |
| `load_denoiser` | boolean | `true` | 是否加载 denoiser |
| `device_map` | string | `auto` | 设备映射 |
| `reference_wav_path` | string | 无 | 克隆参考音频 |
| `prompt_wav_path` | string | 无 | ultimate clone prompt 音频 |
| `prompt_text` | string | 无 | prompt 音频文本 |

### 8.3 TTS API 约束

当前 `/tts/synthesize` 兼容字段：

```json
{
  "engine": "edge",
  "model": "default",
  "voice": "zh-CN-XiaoxiaoNeural",
  "speed": 1.0,
  "common_options": {},
  "provider_options": {}
}
```

新约束：

- `voice/speed` 是便捷字段，只能映射进 `common_options`。
- `engine` 是兼容名，内部统一映射为 `provider`。
- 新增 TTS 参数不得继续加顶层字段，必须进入 `common_options` 或 `provider_options`。
- `voice_profile_id` 不再作为 pipeline 顶层字段扩张，应进入 `profiles.tts.provider_options.voice_profile_id`。

## 9. Artifact / Preview 字段契约

当前 ArtifactRecord 已有：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `artifact_id` | string | 是 | 产物 id |
| `task_id` | string | 是 | 来源任务 |
| `artifact_type` | string | 是 | 例如 `audio.mix` / `subtitle.vtt` |
| `path` | string | 是 | 本地路径 |
| `label` | string | 是 | UI 展示名 |
| `preview_kind` | string | 是 | `audio` / `subtitle` / `text` / `folder` / `none` |
| `stage` | string | 是 | 来源阶段 |
| `is_primary` | boolean | 是 | 是否主产物 |
| `metadata` | object | 是 | 扩展信息 |

约束：

- `artifact_type` 使用点分命名。
- `preview_kind` 决定 UI 行为。
- `is_primary=true` 最多一个；如果多个候选，后端必须决定主产物。
- TaskCenter 必须优先消费 `primary_output` 或 `is_primary`，不得猜路径。

## 10. 前端字段约束

### desktop API type

`desktop/src/api/types.ts` 必须跟 API JSON 同步。

需要补齐：

- `TaskStatusResponse.stage`
- `TaskStatusResponse.error`
- `TaskStatusResponse.created_at`
- `TaskStatusResponse.started_at`
- `TaskStatusResponse.finished_at`
- `TaskStatusResponse.artifact_set_id`
- `TaskStatusResponse.task_type`
- `TaskStatusResponse.task_source`
- `TaskStatusResponse.session_id`

### TaskStore

TaskStore 可以保留本地 `id`，但必须明确：

| 字段 | 说明 |
|---|---|
| `id` | 前端本地 id |
| `serverTaskId` | 后端 `task_id` |
| `status` | 映射自 `state` |
| `stage` | 映射自后端 `stage`，不得再猜 |
| `progress` | 建议存 `0-100` 仅用于 UI；如保留必须标明是 UI progress |

推荐后续将 TaskStore 内部进度也统一为 `0.0-1.0`，渲染层再转百分比。

## 11. 迁移顺序

1. 扩展 `TaskStatus` 和 API schema，保持旧字段兼容。
2. 更新 `desktop/src/api/types.ts` 和 TaskStore。
3. 修改 pipeline progress 回写，写入显式 `stage`。
4. 修改 `PipelineService.create_pipeline_task_spec()`，生成新 ExecutionProfile。
5. 修改 planner，优先消费新 profile，兼容旧 profile。
6. 收紧 TTS 字段，新增参数只进 `common_options/provider_options`。
7. TaskCenter 改用 `stage + artifacts + preview`。

## 12. 验收标准

字段契约落地完成，当且仅当：

- 后端 TaskStatus 返回显式 `stage`，TaskCenter 不再猜阶段。
- 后端 progress 在 API 层统一为 `0.0-1.0`。
- Workbench 不再向 pipeline 顶层追加 provider 私有字段。
- TTS 新参数只出现在 `common_options/provider_options`。
- `ExecutionProfile` 新结构成为默认生成结构。
- `/pipeline/run`、`voice_profile_id`、`engine_params` 等旧入口字段只作为兼容映射存在。
- Artifact / Preview 成为 TaskCenter 结果展示唯一事实源。
