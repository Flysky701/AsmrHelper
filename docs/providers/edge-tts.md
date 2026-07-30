# Provider 简要记录：`edge`

## 基本信息

| 项目 | 内容 |
|---|---|
| category / provider | `tts` / `edge` |
| 官方来源 | <https://github.com/rany2/edge-tts> |
| 查询日期 | `2026-07-30` |
| 项目锁定版本 | `edge-tts==7.2.8` |
| 上游入口 | `edge_tts.Communicate(...)` |

## 项目参数映射

| 项目参数 | 上游参数 | 默认值 | 转换或限制 |
|---|---|---|---|
| `voice` | `voice` | `zh-CN-XiaoxiaoNeural` | 使用上游 voice ID |
| `speed` | `rate` | `1.0` | 项目倍率 0.5 到 2.0 映射为 `-50%` 到 `+100%` |

上游还支持 `volume`、`pitch`、`boundary`、代理和超时参数。当前主链路没有使用需求，因此暂不进入公开契约。

## 依赖与限制

- 关键依赖：`edge_tts`、FFmpeg、网络连接。
- Edge TTS 输出 MP3，项目使用 FFmpeg 转换为 WAV。
- 服务端参数格式错误可能表现为上游 `NoAudioReceived`；项目在请求上游前校验公开参数。
