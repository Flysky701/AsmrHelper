# 外部 TTS

在“设置 → API 配置 → 外部语音合成”命名配置，填写基础地址（通常包含 `/v1`）和 API Key，保存并启用后在工作台按名称选择。TTS 使用独立凭据，不复用翻译密钥；同一配置的空密钥写入保留原值，新建配置不继承其他配置密钥，公开设置只返回是否已配置。

当前界面仅提供 OpenAI 兼容语音接口的简洁配置入口，模型 ID、音色和语音指令暂不展示。底层保留已有参数，但保存地址与密钥并不代表模型参数已适配；具体选项需按服务商文档或可靠探测提供。以下是底层适配器的协议范围，不是当前界面的服务选项清单。

两种接口格式：

| 格式 | 请求及返回 |
| --- | --- |
| OpenAI 兼容语音接口 | `POST /audio/speech`，发送 `model/input/voice/response_format`，读取二进制音频 |
| MiMo 兼容聊天音频接口 | `POST /chat/completions`，合成文本置于 assistant 消息，读取 `choices[0].message.audio.data` 的 Base64 音频 |

模型、音色与指令参数以账号实际可用能力和服务商文档为准，不能因接口兼容而推断服务支持所有字段。聊天音频适配器不发送数值 speed；标准语音接口仅在非默认速度时发送 speed，非空时发送 instructions。当前测试使用模拟响应，未在真实 MiMo 或其他外部服务账户上完成合成验收。

请求 WAV，并校验、解码返回音频后按输出扩展名保存；流水线沿用通用分段合成和时间线对齐。当前实现非流式合成，连接超时 15 秒、读取超时 180 秒。错误不回显服务端响应正文，以免泄漏凭据或文本。

此接入面向语音合成，不扩展现有 Qwen 音色实验室的设计与克隆功能。

协议来源：[OpenAI Text to speech](https://developers.openai.com/api/docs/guides/text-to-speech)、[MiMo Speech Synthesis](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5)。
