# Ryza 语音工程源码核查

核查日期：2026-09-24。仅静态阅读公开源码，未运行上游应用。Bilibili 用户空间未能读取，不能确认视频所用版本、音色及设置。

固定版本：
- AgentAtelierR: `e21983763d83835f6fd3aa2c97aed57cba1d06c9`
- ryza-ai-revive: `0cf1e6147e1ce553dfe2f50151a65b1e45db87c3`

## AgentAtelierR

主要文件：`lib/src/app_controller.dart`、`ai_services.dart`、`chat_segments.dart`、`speech_planner.dart`、`chat_screen.dart`、`continuous_asmr_page.dart`、`tap_reaction.dart`。

### Fish 默认配置与请求

- endpoint: `https://api.fish.audio/v1/tts`
- model header: `s2-pro`
- ASMR reference_id: `c5de0b3f9ac54e08b21fb63120e4ebdb`，空配置回退此值；普通音色默认空。
- format: `mp3`; latency: `normal`; speed: `1.0`。
- request: `normalize: true`, `prosody: {speed: clamp(0.5,2.0), volume: 0.0, normalize_loudness: true}`。
- temperature 与应用情感档位映射：关闭 .55、克制 .62、自然 .70、鲜明 .80、戏剧化 .90。这是应用自定映射，不是经验证的 Fish 情感强度标尺。
- 默认情感 natural、标签密度 normal、independentSpeechPerformance=true。
- 上述描述为客户端实际发送的字段；未验证当前服务端是否接受、如何解释全部字段，也未验证默认音色现在是否可访问。

### 两阶段语音规划

独立 SpeechPlanner 接收原台词、上一轮情绪与共享上下文，只返回句 ID、情绪、标签及 UTF-16 插入偏移。客户端由不可变原文重建台词，验证 ID、白名单、密度、重复标签及代理对边界，避免规划器重写台词；规划失败回退本地规则。

ASMR 倾向使用 whispering、breathy、soft breathy voice、short pause 等；传统提示词也包含 near-whisper。提示词出现不等于所有路径均支持同一标签。

本地 applyFishEmotionIntensityPerSentence：
- off/sparse 不定期重复继承情绪；normal 每 3 句、frequent 每 2 句、everySentence 每句；显式情绪仍可触发。
- 发声标签限额：off 0；sparse 全段 1；normal 每句 1；frequent 每句 2；everySentence 此层不实际限额（999）。独立规划器仍有每句最多 2 个等约束，不能只看单层。
- ASMR 且密度非 off 时，非 natural/off 情感档位把主情绪改写成包含 very quiet whispering、emotional phrasing、breath timing、voice hushed 的自由描述。
- natural 保留 `[emotion]`，不会进入强化描述；off 去掉主情绪。不能理解为打开 ASMR 就必定前置强化耳语指令。

### 播放及功能

- 普通聊天在播放本句前启动下一段语音准备，降低句间等待。
- 持续 ASMR：每轮 1–2 句、合计不超过 60 字，预取下一轮 LLM 文本，逐轮合成与播放；最多保留 50 个片段，有定时停止。该页预取文本不等于提前生成下一轮音频。
- 触碰音频按 `audio/tap_voice/<locale>/<normal|asmr>/...m4a` 选择，每项变体夹在 1–3；这是本地素材选择，不是普通声音实时转耳语。
- 当前核查的播放链路没有发现 HRTF、卷积双耳渲染或通用语音转耳语 DSP。

## ryza-ai-revive

- `web/js/api.js`: ASMR 可用独立 fishVoiceAsmr，空值回退普通音色。
- MODE_TTS 给 OpenAI/MiMo 风格路径、Qwen instruct 路径添加日语模式指令；不能据此推定现代 Fish 路径收到相同 instruction。
- 现代 Fish synthModern 只组装 text、format、可选 reference_id，模型放 header；没有 AgentAtelierR 上述 temperature/prosody 请求组装。
- ASMR 播放 rate=.93、gain=.82；沉浸模式 rate=.97、gain=.95。app.js 实际设置 HTMLAudioElement.playbackRate 和基础音量乘 gain。
- Web Audio 图为媒体源→Analyser→destination，用于分析；未发现这一路进行双耳空间处理。

## 对本项目的建议

之前测试使用 Yutong/小温 ASMR 和 s2.1-pro-free，不是上游默认音色与模型，不能视为复现或否证。

优先做可复现配置实验：固定同一中文短句，验证上游 reference_id；在可用模型上比较无标签、简单 whispering、按源码克制档组织的完整描述。将模型差异单独标记，不能把跨模型/跨音色变化归因于标签。随后比较重复生成的一致性、漏字、音色保持及耗时。

适合移植的功能：不可改写台词的演绎规划、标签白名单与密度控制、normal/asmr 双音色槽、下一句预生成与取消、短句连续播放、参数留档和 A/B。空间化是我们可新增的功能，不是已证实的上游秘诀。

复用边界：ryza-ai-revive 根目录有 MIT LICENSE。AgentAtelierR 根目录本次未见 LICENSE，README 强调资源各自授权；先独立实现工程思想，不直接搬运源码或角色音频。
