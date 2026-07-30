# Provider 简要记录：`faster_whisper`

## 基本信息

| 项目 | 内容 |
|---|---|
| category / provider | `asr` / `faster_whisper` |
| 官方来源 | <https://github.com/SYSTRAN/faster-whisper> |
| 查询日期 | `2026-07-30` |
| 项目锁定版本 | `faster-whisper==1.2.1` |
| 上游入口 | `WhisperModel(...)` / `WhisperModel.transcribe(...)` |

## 项目参数映射

| 项目参数 | 上游参数 | 默认值 | 转换或限制 |
|---|---|---|---|
| `language` | `language` | `ja` | `auto` 转为 `None`，由模型检测 |
| `vad_filter` | `vad_filter` | `false` | ASMR 默认保留轻声；启用时传入项目 VAD 参数 |
| `beam_size` | `beam_size` | `5` | 必须大于等于 1 |
| `initial_prompt` | `initial_prompt` | 无 | 不再硬编码日语提示词 |
| `no_speech_threshold` | `no_speech_threshold` | `0.9` | 范围 0 到 1，用于保留轻声 |

## 模型与依赖

- Model ID：`faster-whisper-tiny/base/small/medium/large-v3`
- 本地资源：`config/models.yaml` 中对应的 `faster-whisper-*`
- 关键依赖：`faster_whisper`、CTranslate2 模型文件
- 默认不启用 VAD；这与普通语音转录偏好不同，是当前 ASMR 主链路选择。
