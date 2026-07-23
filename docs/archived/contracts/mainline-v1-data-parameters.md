# [已归档] AsmrHelper 主链路 V1 数据参数契约

日期：2026-05-27

## 1. 契约目的

本文补充 [主链路 V1 契约](mainline-v1-contract.md) 中没有完全展开的数据参数定义。

横向字段约束以 [字段契约约束 V1](field-contracts-v1.md) 为准；本文只展开主链路对象和兼容字段映射。

当前阶段需要先固定三件事：

- Workbench 创建任务时提交哪些字段。
- 后端冻结任务时保存哪些字段。
- 执行器运行时消费哪些字段。

本文只定义主链路 V1 的最小稳定参数，不追求覆盖所有 provider 私有能力。provider 专属参数仍由 [配置与提供方接入管理](../domains/06-configuration-provider-management.md) 中的 `CapabilityDescriptor` 扩展。
日志事件、模型资源字段、高级参数 schema、敏感参数和 RuntimeBinding 的横向边界见 [基础设施契约 V1](infrastructure-contracts-v1.md)。

## 2. 参数分层

主链路 V1 参数分为四层。

| 层级 | 对象 | 生成方 | 消费方 | 是否持久化 |
|---|---|---|---|---|
| 输入会话 | `Session` / `InputAsset` | Workbench + 输入管理 | 任务系统、pipeline 执行器 | 是 |
| 任务定义 | `TaskSpec` | 任务系统 | 队列、调度器、执行器 | 是 |
| 执行配置 | `ExecutionProfile` | 配置中心 + 任务系统 | pipeline 执行器、工具执行器 | 是 |
| 运行时绑定 | `RuntimeBinding` | 配置中心 + 资源管理 | 执行器 | 否 |

关键规则：

- `TaskSpec` 保存“这次任务要怎么跑”。
- `ExecutionProfile` 保存可审计、可复现的非敏感参数。
- `RuntimeBinding` 只在执行时注入 API key、base URL、本地模型路径、device 等运行条件。
- Workbench 不直接保存 provider 私有语义，只提交用户选择和覆盖项。

## 3. 通用字段规范

| 字段类型 | 规则 |
|---|---|
| id | 使用带前缀字符串，例如 `session_xxx`、`asset_xxx`、`task_xxx` |
| 时间 | ISO 8601 字符串，带时区，例如 `2026-05-27T12:00:00+08:00` |
| 路径 | 桌面端可以使用本地绝对路径；跨进程传输时必须保持 UTF-8 |
| 语言 | 使用 BCP 47 或项目约定短码，例如 `ja`、`zh`、`zh-CN` |
| 比例 | 音量、语速等使用数字，不使用百分号字符串 |
| 布尔 | 使用 JSON boolean，不使用 `"true"` / `"false"` 字符串 |
| 可选字段 | 不确定时省略字段，不用空字符串表达未知 |

## 4. SessionCreateRequest

Workbench 在创建任务前，应先把输入整理为会话。

```json
{
  "source": "desktop.workbench",
  "input_path": "D:/input/demo.wav",
  "output_dir": "D:/output",
  "discover_companions": true,
  "output_policy": {
    "mode": "near_input",
    "overwrite": false
  }
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `source` | string | 是 | 无 | 调用来源，Workbench 固定为 `desktop.workbench` |
| `input_path` | string | 是 | 无 | 主输入文件路径 |
| `output_dir` | string | 否 | 系统默认输出目录 | 显式输出目录 |
| `discover_companions` | boolean | 否 | `true` | 是否自动发现同名字幕或脚本 |
| `output_policy.mode` | string | 否 | `near_input` | 输出目录策略，V1 支持 `near_input` / `custom` |
| `output_policy.overwrite` | boolean | 否 | `false` | 是否允许覆盖已有输出 |

## 5. Session

后端返回的会话至少应包含：

```json
{
  "session_id": "session_xxx",
  "workspace_id": "workspace_default",
  "input_asset_id": "asset_audio",
  "companion_asset_ids": ["asset_subtitle"],
  "output_dir": "D:/output",
  "temp_dir": "D:/output/.asmrhelper/session_xxx",
  "created_at": "2026-05-27T12:00:00+08:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | string | 是 | 输入会话 id |
| `workspace_id` | string | 是 | 所属工作空间 |
| `input_asset_id` | string | 是 | 主输入资产 id |
| `companion_asset_ids` | string[] | 是 | 伴随字幕、脚本等资产 id 列表，可为空数组 |
| `output_dir` | string | 是 | 本次任务默认输出目录 |
| `temp_dir` | string | 是 | 本次任务临时目录 |
| `created_at` | string | 是 | 创建时间 |

## 6. InputAsset

```json
{
  "asset_id": "asset_audio",
  "kind": "audio",
  "path": "D:/input/demo.wav",
  "display_name": "demo.wav",
  "media_type": "audio/wav",
  "size_bytes": 10485760,
  "duration_ms": 185000,
  "language_hint": "ja"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `asset_id` | string | 是 | 资产 id |
| `kind` | string | 是 | V1 支持 `audio` / `subtitle` / `script` / `folder` |
| `path` | string | 是 | 本地路径 |
| `display_name` | string | 是 | UI 展示名 |
| `media_type` | string | 否 | MIME 类型 |
| `size_bytes` | number | 否 | 文件大小 |
| `duration_ms` | number | 否 | 音频时长 |
| `language_hint` | string | 否 | 输入语言提示 |

## 7. TaskCreateRequest

Workbench 创建 pipeline 任务时提交：

```json
{
  "task_type": "pipeline",
  "task_source": "desktop.workbench",
  "session_id": "session_xxx",
  "input_asset_id": "asset_audio",
  "companion_asset_ids": ["asset_subtitle"],
  "execution_profile": {
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
      "separator": {
        "category": "separator",
        "provider": "demucs",
        "model": "htdemucs",
        "common_options": {
          "mode": "vocals"
        },
        "provider_options": {}
      },
      "asr": {
        "category": "asr",
        "provider": "faster_whisper",
        "model": "base",
        "common_options": {
          "language": "ja",
          "output_format": "segments",
          "timestamps": true
        },
        "provider_options": {}
      },
      "translation": {
        "category": "llm",
        "provider": "deepseek",
        "model": "default",
        "common_options": {
          "source_lang": "ja",
          "target_lang": "zh-CN",
          "preserve_timestamps": true
        },
        "provider_options": {}
      },
      "tts": {
        "category": "tts",
        "provider": "edge_tts",
        "model": "default",
        "common_options": {
          "voice": "zh-CN-XiaoxiaoNeural",
          "speed": 1.0
        },
        "provider_options": {}
      },
      "mix": {
        "category": "mix",
        "provider": "local",
        "model": "default",
        "common_options": {
          "original_volume": 0.85,
          "tts_volume_ratio": 0.5,
          "tts_delay": 0.0,
          "normalize": true
        },
        "provider_options": {}
      },
      "export": {
        "category": "export",
        "provider": "local",
        "model": "default",
        "common_options": {
          "subtitle_format": "vtt",
          "include_intermediate_files": true
        },
        "provider_options": {}
      }
    },
    "skip_existing": false
  },
  "priority": 0,
  "dedupe_key": "pipeline:D:/input/demo.wav:default_ja_to_zh"
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `task_type` | string | 是 | 无 | 主链路固定为 `pipeline` |
| `task_source` | string | 是 | 无 | Workbench 固定为 `desktop.workbench` |
| `session_id` | string | 是 | 无 | 输入会话 id |
| `input_asset_id` | string | 是 | 无 | 主输入资产 id |
| `companion_asset_ids` | string[] | 是 | `[]` | 伴随资产 id |
| `execution_profile` | object | 是 | 无 | 本次任务冻结参数 |
| `priority` | number | 否 | `0` | 队列优先级，数字越大优先级越高 |
| `dedupe_key` | string | 否 | 后端生成 | 去重键 |

## 8. ExecutionProfile

`ExecutionProfile` 是本契约最重要的数据参数对象。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `profile_version` | string | 是 | `mainline.v1` | 参数版本 |
| `source_lang` | string | 是 | 系统默认 | 源语言 |
| `target_lang` | string | 是 | 系统默认 | 目标语言 |
| `preset_id` | string | 否 | 无 | 仅表示参数模板来源，不作为执行语义 |
| `stages` | object | 是 | 无 | 各阶段是否启用 |
| `profiles` | object | 是 | 无 | 各阶段标准 profile |
| `skip_existing` | boolean | 否 | `false` | 是否跳过已有输出 |

### stages

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `separate` | boolean | 是 | `true` | 是否执行人声分离 |
| `asr` | boolean | 是 | `true` | 是否执行语音识别 |
| `translate` | boolean | 是 | `true` | 是否执行字幕翻译 |
| `tts` | boolean | 是 | `true` | 是否执行语音合成 |
| `mix` | boolean | 是 | `true` | 是否执行混音 |
| `export` | boolean | 是 | `true` | 是否导出产物索引和字幕 |

### profile 通用结构

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `category` | string | 是 | 能力类别，例如 `asr` / `tts` / `llm` |
| `provider` | string | 是 | provider id |
| `model` | string | 是 | provider 下的模型或档位 |
| `common_options` | object | 是 | 跨 provider 的公共参数 |
| `provider_options` | object | 是 | provider 私有参数，可为空对象 |

## 9. V1 公共参数表

### separator.common_options

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `mode` | string | `vocals` | 分离目标，V1 支持 `vocals` |

### asr.common_options

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `language` | string | `source_lang` | 识别语言 |
| `output_format` | string | `segments` | V1 使用 `segments` 作为后续字幕和 TTS 的基础 |
| `timestamps` | boolean | `true` | 是否保留时间戳 |

### translation.common_options

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `source_lang` | string | 顶层 `source_lang` | 源语言 |
| `target_lang` | string | 顶层 `target_lang` | 目标语言 |
| `preserve_timestamps` | boolean | `true` | 是否保持字幕段落时间轴 |
| `style` | string | `natural` | 翻译风格，V1 不强制复杂枚举 |

### tts.common_options

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `voice` | string | provider 默认音色 | TTS 音色或 speaker |
| `voice_profile_id` | string | 无 | 可选，引用已保存 voice profile |
| `speed` | number | `1.0` | 语速倍率 |
| `language` | string | 顶层 `target_lang` | 合成语言 |

### mix.common_options

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `original_volume` | number | `0.85` | 原音轨音量倍率 |
| `tts_volume_ratio` | number | `0.5` | TTS 音量倍率 |
| `tts_delay` | number | `0.0` | TTS 延迟秒数 |
| `normalize` | boolean | `true` | 是否做基础响度归一 |

### export.common_options

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `subtitle_format` | string | `vtt` | 字幕导出格式，V1 支持 `vtt` / `srt` |
| `include_intermediate_files` | boolean | `true` | 是否索引中间产物 |

## 10. RuntimeBinding

`RuntimeBinding` 不进入任务记录，只在执行时生成。

```json
{
  "task_id": "task_xxx",
  "bindings": {
    "asr": {
      "local_model_path": "D:/models/faster-whisper/base",
      "device": "cuda"
    },
    "translation": {
      "base_url": "https://api.example.com",
      "api_key_ref": "provider.deepseek.api_key"
    },
    "tts": {
      "runtime_client": "edge_tts"
    }
  }
}
```

规则：

- `api_key_ref` 可以记录引用名，但不得把明文 API key 写入任务、日志或普通查询响应。
- 本地模型路径、device、client 对象都属于执行时环境，不作为 Workbench 参数。
- 执行器缺少 runtime binding 时，应返回结构化错误，而不是回退到隐式默认值。

## 11. 旧字段映射

兼容旧接口时，应在适配层完成字段映射。

| 旧字段 | 新位置 |
|---|---|
| `input_path` | `SessionCreateRequest.input_path` |
| `output_dir` | `SessionCreateRequest.output_dir` |
| `source_lang` | `ExecutionProfile.source_lang` |
| `target_lang` | `ExecutionProfile.target_lang` |
| `use_vocal_separator` | `ExecutionProfile.stages.separate` |
| `vocal_model` | `ExecutionProfile.profiles.separator.model` |
| `asr_model` | `ExecutionProfile.profiles.asr.model` |
| `translate_provider` | `ExecutionProfile.profiles.translation.provider` |
| `tts_engine` | `ExecutionProfile.profiles.tts.provider` |
| `tts_voice` | `ExecutionProfile.profiles.tts.common_options.voice` |
| `original_volume` | `ExecutionProfile.profiles.mix.common_options.original_volume` |
| `tts_volume_ratio` | `ExecutionProfile.profiles.mix.common_options.tts_volume_ratio` |
| `tts_delay` | `ExecutionProfile.profiles.mix.common_options.tts_delay` |
| `skip_existing` | `ExecutionProfile.skip_existing` |

## 12. 前端参数边界

Workbench 可以展示和编辑：

- 输入文件、输出目录和输出策略。
- 源语言、目标语言、预设。
- 阶段启停。
- provider、model、voice、speed、mix 音量等公共参数。
- 由 `CapabilityDescriptor` 暴露的 provider 私有参数。

Workbench 不应展示或保存：

- API key 明文。
- 本地模型最终解析路径。
- runtime client 对象。
- 执行器内部临时路径。
- 通过日志文本反推出来的状态或产物路径。

TaskCenter 可以展示：

- `TaskStatus`。
- `ArtifactSet`。
- `Preview`。
- 脱敏后的执行参数快照。

TaskCenter 不应直接编辑已冻结任务的 `ExecutionProfile`。重试时如需改参数，应创建新的任务或明确生成新的 profile 版本。

## 13. 验收标准

数据参数契约完成，当且仅当：

- Workbench 创建任务只依赖本文定义的请求字段。
- 旧接口字段能明确映射到 `Session`、`TaskSpec` 或 `ExecutionProfile`。
- 执行器只消费 `ExecutionProfile` 与执行时注入的 `RuntimeBinding`。
- TaskCenter 展示参数快照时不泄露敏感凭据。
- 新增 provider 私有参数时，只扩展 `provider_options` 和 `CapabilityDescriptor`，不污染主链路公共字段。
