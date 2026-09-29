> 历史材料，归档于 2026-09-30。记录当时设计或验收，不作为当前配置及接入指南。TTS 当前入口：[统一 TTS 指南](../../guides/tts.md)。

# 外部 TTS

在“引擎与资源 → 外部服务 → 外部语音合成”命名配置，保存并启用后在工作台按名称选择。TTS 使用独立凭据，不复用翻译密钥；同一服务的空密钥写入保留原值，更换主机或协议需要重新填写密钥。新建配置不继承其他配置密钥，公开设置只返回是否已配置。

界面提供通用 OpenAI 兼容接口和 Fish Audio 官方接口。通用接口的模型、音色及指令按服务商文档填写；Fish 提供官方文档中的模型选项，不猜测音色列表。既有 MiMo 配置保持原协议，本次不新增 MiMo 专用配置。

接口格式：

| 格式 | 请求及返回 |
| --- | --- |
| OpenAI 兼容语音接口 | `POST /audio/speech`，发送 `model/input/voice/response_format`，读取二进制音频 |
| MiMo 兼容聊天音频接口 | `POST /chat/completions`，合成文本置于 assistant 消息，读取 `choices[0].message.audio.data` 的 Base64 音频 |
| Fish Audio 官方接口 | `POST /tts`，`model` 放在请求头，发送 `text/reference_id/format`，读取二进制音频 |

Fish 配置：基础地址 `https://api.fish.audio/v1`；模型默认 `s2.1-pro-free`，也可选 `s2.1-pro`、`s2-pro`、`s1`，具体账号权限以服务端为准。音色 ID 填写 Fish 平台实际的 `reference_id`。使用 Bearer 鉴权，非默认语速通过 `prosody.speed` 发送，范围为 0.5–2.0。Fish 不支持独立 `instructions` 字段；需要风格标签时按官方文档写在合成文本中。保存配置不等于真实合成已验证。

模型、音色与指令参数以账号实际可用能力和服务商文档为准，不能因接口兼容而推断服务支持所有字段。聊天音频适配器不发送数值 speed；标准语音接口仅在非默认速度时发送 speed，非空时发送 instructions。Fish 适配测试覆盖配置保存、任务快照、HTTP 请求和音频解码，使用模拟响应；尚未使用真实账户验证本项目的新适配器。

请求 WAV，并校验、解码返回音频后按输出扩展名保存；流水线沿用通用分段合成和时间线对齐。当前实现非流式合成，连接超时 15 秒、读取超时 180 秒。错误不回显服务端响应正文，以免泄漏凭据或文本。

此接入面向语音合成，不扩展现有 Qwen 音色实验室的设计与克隆功能。

协议来源：[OpenAI Text to speech](https://developers.openai.com/api/docs/guides/text-to-speech)、[MiMo Speech Synthesis](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5)。

Fish 来源（核对日期 2026-09-24）：[官方 TTS API](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech)、[官方 SDK 参数](https://github.com/fishaudio/fish-audio-go/blob/main/tts.go)。
