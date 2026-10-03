> 历史调研及验收材料，归档于 2026-09-30。旧代码路径、参数及探测命令已被替代；当前入口：[统一 TTS 指南](../../guides/tts.md)。

# 耳语 TTS 功能探索与接入评估

调研日期：2026-09-23；实验更新：2026-09-24。状态：Qwen3 耳语选项已接入并完成三组真实合成，尚未完成耳语听感及完整视频验收。实测结果见文末。

## 结论

建议加入实验性的“中文耳语配音”能力。第一候选为项目已有的 Qwen3-TTS 1.7B CustomVoice，第二候选为已有适配器的 VoxCPM2；只有两者听感不达标时，再评估新增 CosyVoice Provider。Fish Speech S2 Pro 有明确耳语标签，但许可证和部署成本使它更适合作为可选对照。

用户描述最吻合的产品是 SpiralAI 的 RyzaChat:AI。官方确有 ASMR 模式，但本轮没有找到其官方语音模型的开源权重或训练、推理仓库。能复用的是公开 TTS 项目的风格控制能力，不能承诺复现莱莎原声或官方同等听感。

补充核查：用户明确要求检查同名开源项目 `zeroa234/ryza-ai-revive`。已读到其 ASMR 相关源码，确认可借鉴风格组合、专用音色选择及播放调节；未发现这条已检查链路包含自有耳语模型或原生双耳生成器。具体复用判断见第 9 节。

本项目处理日文 ASMR 汉化，耳语中文配音与现有目的直接一致。无需为了这个功能引入聊天人格、立绘、记忆或实时对话系统。

## 1. 产品与开源项目辨认

| 对象 | 查证结果 | 对本项目的意义 |
| --- | --- | --- |
| [RyzaChat:AI 官网](https://ryzachat-ai.go-spiral.ai/tw) | 提供文字、语音、ASMR 三种交互；说明语音基于声优同意的专门录音 | 功能参照；官网没有给出可下载模型或可复现耳语架构 |
| [SpiralAI 的 Kotodama 发布说明](https://prtimes.jp/main/html/rd/p/000000071.000120221.html) | 公司自行开发的语音合成服务，提供 API | 商业服务线索；不能据此假定公共 API 开放莱莎音色或同款 ASMR 能力 |
| [zeroa234/ryza-ai-revive](https://github.com/zeroa234/ryza-ai-revive) | MIT 客户端；已核查 `master` 上的 api.js、app.js、providers.js、audio.js、alarm.js | 有 ASMR 编排实现，但不是官方模型开源证据，也不是独立耳语推理引擎 |

“耳语”在这里指合成语音的发声风格，不是本项目 Faster-Whisper 的语音识别功能。

## 2. 需要拆开的能力

1. **耳语发声**：由 TTS 的指令、参考录音或训练数据决定，包含气声、弱声带振动和相应韵律。单纯降低普通朗读音量不能替代它。
2. **轻声与停顿**：语速、句间停顿、呼吸保留和整体响度；轻柔语音不必然是真正耳语。
3. **左右耳空间感**：立体声声像、距离感，进一步可使用 HRTF。这是后处理与声道保存问题，不能用“双声道文件”直接等同于双耳录音。

以上是工程拆分，不是对 RyzaChat 私有实现的推断。首版只承诺尝试第 1、2 项，第 3 项作为单独阶段。

## 3. 候选比较

| 候选 | 已核实的控制方式 | 接入判断 | 限制 |
| --- | --- | --- | --- |
| Qwen3-TTS 1.7B CustomVoice / VoiceDesign | 自然语言 `instruct`；预设音色与设计音色分别使用不同方法 | **首选实验**，已有 Worker、模型资源、音色和 Pipeline 链路 | 指令支持不代表中文耳语已经验收；0.6B CustomVoice 不支持同样的指令控制；Base 克隆不是同一能力 |
| VoxCPM2 | `text` 前置括号描述；可结合 `reference_wav_path` 控制克隆风格 | **第二候选**，已有 Provider，可以补齐风格参数 | 当前未见专门耳语质量证据；项目适配器尚无独立风格字段，部署和听感需实测 |
| Fun-CosyVoice3-0.5B-2512 | `inference_instruct2(text, instruct_text, prompt_wav, ...)`；官方指令表包含 very soft voice | 备选，适合参考音频结合轻声控制 | 官方表中轻声不等于耳语；要增加独立运行时、资源、适配器和 readiness |
| Fish Speech S2 Pro | 官方明确展示 `[whisper]` 等行内标签 | 耳语能力明确的**可选对照** | 采用 Fish Audio Research License，商业使用需另外授权，不能按 MIT/Apache 模型默认打包 |
| 现有外部 TTS | `openai_compatible` 已传递 `instructions` | 最快的服务对照通道 | 仅接口兼容不保证服务端遵循耳语指令；也不意味着 Fish/CosyVoice 原生接口可直接套用 |

上游依据：[Qwen 仓库与型号表](https://github.com/QwenLM/Qwen3-TTS)、[Qwen 推理源码](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py)、[VoxCPM2 用法](https://github.com/OpenBMB/VoxCPM)、[CosyVoice 示例](https://github.com/QwenAudio/CosyVoice/blob/main/example.py)、[CosyVoice 指令表](https://github.com/QwenAudio/CosyVoice/blob/main/cosyvoice/utils/common.py)、[Fish Speech](https://github.com/fishaudio/fish-speech)。这些是调研当日的公开版本，实施时必须固定 revision 并复核接口。

许可证分别核对：[Qwen 1.7B CustomVoice 模型卡](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)、[VoxCPM2 模型卡](https://huggingface.co/openbmb/VoxCPM2)、[CosyVoice3 模型卡](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512) 均标记 Apache-2.0；[Fish 当前 LICENSE](https://github.com/fishaudio/fish-speech/blob/main/LICENSE) 有研究/非商业条件及商业授权要求。模型许可不提供莱莎角色或声优素材的使用授权；实验使用预设音色或用户有权使用的录音即可。

## 4. 当前项目源码的实际接入点

审阅对象为当前工作树，包含已有未提交改动；本轮没有修改它们。锁文件为 `qwen-tts==0.1.1`、`voxcpm==2.0.3`，不能把最新上游全部能力直接视作当前已接入能力。

| 位置 | 实际发现 | 实施含义 |
| --- | --- | --- |
| `src/core/tts/__init__.py`：`Qwen3TTSEngine.__init__`、`_synthesize` | 预设 profile 的 `instruct` 会传入 `generate_custom_voice` | 有可复用的底层能力；宜增加显式的请求级风格参数和优先级 |
| `desktop/src/pages/voice-lab/VoiceLab.tsx`：语气控制面板 | 有输入框，但保存按钮禁用，提示后端没有更新接口 | 当前不能让用户填耳语指令后假定已保存、生效 |
| `src/app/services/capability_descriptor_service.py`：qwen3 | 声明 `voice_profile_id`、`emotion`、`temperature`，未声明通用 `instruct` | 需从能力描述、请求校验到 Worker、引擎完整接线 |
| `src/core/tts/__init__.py`：`synthesize_with_instruct` 与超长句分支 | 加速重合成传入新的速度指令，未合并原风格 | 可能丢失耳语；需合并基础风格与速度指令并验证 |
| `src/core/tts/__init__.py`：custom/clone 分支 | 使用 Base 的 `generate_voice_clone`，不消费风格指令 | 不可给所有音色显示同一耳语开关；克隆需耳语参考或另选可控克隆引擎 |
| `src/core/tts/voice_designer.py` | VoiceDesign 先生成参考音频，再创建 Base clone prompt | 初次设计为耳语不保证所有后续句子保持耳语，要单独评测持续性 |
| `src/core/engines/tts/voxcpm2.py` | 传文本与参考音频，没有专门风格参数 | 可以在 Provider 内映射括号描述；不应把控制文本写入字幕正文 |
| `src/core/tts/__init__.py`：时间线组装 | 多声道取平均，最后复制为相同左右声道 | 当前 Qwen/Edge 时间线不是双耳渲染，且会丢弃输入中的空间信息 |
| `src/core/engines/tts/service.py`：通用时间线 | 多声道取平均，输出单声道时间线 | 外部立体声音频也不能自动保留；双耳阶段需覆盖此路径 |
| `src/mixer/__init__.py`：`Mixer.mix` | 以原声与 TTS 的整体 RMS 计算增益 | 可能把低响度耳语抬高，影响近耳听感；需比较自动增益与固定增益，而非断言必然失效 |
| `src/core/engines/tts/openai_compatible.py` | 标准语音接口传 `instructions`，另一接口格式映射为消息 | 可用现有设置做外部服务对照，仍需服务端真实验证 |

还有一个参数陷阱：不能简单把 `instruct` 塞入 Qwen 的 `**kwargs`。当前会保存在 `extra_options`，调用时又显式传 `instruct=...`，会发生重复关键字的 TypeError；随后回退路径去掉额外参数，可能让新指令被丢弃。应显式接收、解析并只传递一次。

## 5. 推荐的最小产品方案（尚未实现）

将“普通 / 轻声 / 耳语（实验）”设为 TTS 风格预设，底层映射为引擎自己的控制方式；首版采用全任务风格，不引入自动逐句风格识别。

- 首先支持 Qwen3 1.7B CustomVoice 的试音，沿用 Voice Task 和 Artifact 输出。试音请求应携带当次风格，无须先改写内置音色。
- 再把同一配置加入 `ExecutionProfile`，让工作台、Pipeline 和 BatchRun 共享；不能仅在 UI 保存标签。
- 配置优先级建议为“任务显式指令 > profile 指令 > 空”，加速重合成在已解析的基础风格上追加约束。
- 对 Base 克隆及不支持指令的型号返回清楚的能力限制，不静默当普通朗读执行。
- 保留原始单句 WAV 和时间线 WAV，便于区分模型问题、时长对齐问题和混音问题。
- 双耳阶段另加声像/声道保存策略：先保留原始 ASMR 立体声，再对中文配音选择居中或静态左右定位；HRTF 和自动跟随原音声像后续再做。

实验指令可从“用自然、轻柔的气声耳语朗读，语速舒缓，停顿自然，保持文字清晰”开始。它是待测提示词，不是已验证配方。不建议一开始把“极慢语速”与严格字幕时长同时设为强约束。

## 6. 验证方案与准入条件

先做小样本 A/B，再接长音频；不能仅以 API 成功返回 WAV 判定耳语通过。

1. 选 12 句中文，覆盖短句、长句、疑问句、数字和多停顿句。每句分别生成普通、轻声、耳语，每组重复 2 次，共 72 条；固定模型 revision、音色、参数，并记录可用的随机种子。
2. 同时保留原始响度版和只供盲听的响度匹配版，避免把“更小声”误判为“更像耳语”。评价耳语质感、可懂度、音色稳定性、噪声/爆音与尾字完整性。
3. 用 3 段现有 ASMR 时间线验证：普通句长、中文明显超长、连续快速切句。分别听单句、拼接结果、最终混音。
4. 记录冷启动时间、热合成时间、RTF（合成耗时/音频时长）、峰值显存、失败率、越界时长、削波率和人工听感。ASR 回转文本仅作辅助，不能单独判定耳语质量。
5. 建议准入门槛：耳语盲听评分中位数至少 4/5、无整句漏读与控制词朗读、无明显尾字截断，超长句重合成仍保留风格。阈值是本项目提案，不是行业标准；小样本通过后仍需长素材验收。

当前机器只做了硬件只读探测：RTX 5070 Laptop，显存 8151 MiB。Qwen 历史主链路验收可作为起点，但不代表本轮耳语实测通过。VoxCPM 上游对 VoxCPM2 列出的约 8 GB 显存已接近本机总量，实际峰值、桌面占用和模型共存需要测试；建议顺序运行各引擎，模型按需卸载。[上游资源表](https://github.com/OpenBMB/VoxCPM#model-comparison)

## 7. 工作量与决策

以下为单人熟悉代码、依赖可运行条件下的工程估算，不含训练、模型下载等待和长素材人工听评。

| 阶段 | 预计工作量 | 完成条件 |
| --- | --- | --- |
| Qwen 小样本实验与报告 | 0.5–1 人日 | 形成可听的普通/耳语对照，决定是否继续 |
| Qwen 风格参数、试音、Pipeline 接线及回归 | 2–4 人日 | 参数确实到达上游，Worker/批次/重合成风格一致 |
| VoxCPM2 风格补齐与运行验收 | 1–3 人日 | 当前锁定版本可执行，中文耳语听评有收益 |
| 新增 CosyVoice Provider | 3–6 人日 | 隔离环境、安装、readiness、推理和流水线通过；Windows 依赖问题可能增加时间 |
| 双耳声道保留和基础声像 | 2–4 人日 | 立体声贯穿时间线与导出，单声道兼容；不含完整 HRTF 系统 |

决策：支持立项为实验功能，优先投入 Qwen 验证与参数接线。若耳语听感不达标，先对照 VoxCPM2/Fish，再决定是否付出新增 Provider 的维护成本。首轮不要承诺官方莱莎同款音色、全自动恢复原作空间感或实时聊天。

## 8. 本次调研边界

已完成联网检索、官方文档和部分上游代码核查、本项目调用链审阅及 GPU 型号探测。未下载模型、未调用付费语音服务、未执行真实耳语推理或听感评测。结论是架构可行与候选排序，不是效果验收。只新增本报告与文档索引，不改变运行代码和现有配置。

## 9. 同名开源项目的模块复用审阅

核查仓库：[zeroa234/ryza-ai-revive](https://github.com/zeroa234/ryza-ai-revive)，分支 `master`。读取到的 `config/version.json` 为 1.2.21/code 24；网页缓存的文件时间可能不同，本轮没有取得统一 commit 快照，以下属于源码静态审阅，正式移植前需固定提交再核验。

### 实现证据

| 模块 | 已观察行为 | 复用价值 |
| --- | --- | --- |
| [api.js](https://github.com/zeroa234/ryza-ai-revive/blob/master/web/js/api.js)：`MODE_TTS`、`ttsStyleFor` | 基础音色描述与模式指令组合，ASMR 有单独提示 | 高：移植成后端风格解析器，中文配音需自己的提示模板 |
| 同文件：`_qwenSpeak`、`speak` | 分别向支持指令的 Qwen 云模型与聊天音频接口传风格 | Qwen 云接口不等于本地 qwen-tts；本项目当前只保留已支持的语音 Provider |
| 同文件：`fishVoiceFor`、`_fishSpeak` | ASMR 优先选独立音色 ID；现代 Fish 请求使用 `reference_id` 与模型 header | 可借鉴风格与音色分离；该路径没有自动添加 `[whisper]`，音色未设置时可能仍用普通声音 |
| [app.js](https://github.com/zeroa234/ryza-ai-revive/blob/master/web/js/app.js)：`speakThen`、`playUrl` | 应用 ASMR 播放倍率 0.93、音量乘数 0.82，结束时复位倍率 | 仅是播放效果，不能当作耳语模型；这些调整不会自动写入导出的 WAV |
| 同文件：`_ensureVoiceGraph` | 媒体源接分析器再接输出 | 已检查的图没有声像/HRTF 节点，分析器用于角色嘴型；不能用来补本项目的双耳能力 |
| [providers.js](https://github.com/zeroa234/ryza-ai-revive/blob/master/web/js/providers.js) | Provider 独立凭据与能力标记，Fish 有专用 ASMR 音色字段 | 模式值得借鉴；本项目已有能力目录与 Provider 配置，不必引入第二套注册表 |
| [audio.js](https://github.com/zeroa234/ryza-ai-revive/blob/master/web/js/audio.js)：`tapVoice`、`VoiceBank.pick` | 按普通/ASMR 样式筛选预录素材，缺少时可回退 | 是素材播放，不是任意文本耳语合成；不把其角色音频当通用模型资源 |
| [alarm.js](https://github.com/zeroa234/ryza-ai-revive/blob/master/web/js/alarm.js)：`_tick`、预览回调 | 根据闹钟样式调用 VoiceBank | 闹钟 ASMR 效果不能证明动态 TTS 同样有效 |

### 移植方案

建议复用小模块的设计，按本项目 Python 后端重写，不整包移植浏览器脚本。上游依赖 `window.Config`、`App`、Blob URL 与角色场景，直接引入会增加不必要的耦合。

推荐新增一个纯函数式风格解析层，输入为音色基础描述、任务风格与用户覆盖项，输出为实际合成指令及可选音色 ID。再由各 Provider 适配器转换为自己的参数。字段名属于提案，应沿现有能力描述与 ExecutionProfile 契约落地。

本节记录历史设计判断；专属聊天音频适配器已于 2026-10-03 移除。通用 OpenAI 语音使用标准语音接口，不复用聊天消息音频协议。演绎参数应按当前 Provider 能力验证，并使试听与正式流水线共享同一参数映射。

Fish 原生接口需专门 Provider 或明确的协议适配：不能把它的地址填进现有 `/audio/speech` 就认为接入完成；上游按域名推断协议的逻辑也不宜直接复制给任意自定义服务。必须对照服务商接口确认，不能把第三方客户端常量视作官方契约。

如果复用播放倍率，应将其区分为“仅预览”或后端实际渲染；后者会改变时长，须参与字幕对齐。固定 0.93/0.82 只适合作为对照样本，不能直接作为全项目默认值。

[上游 MIT 许可证](https://github.com/zeroa234/ryza-ai-revive/blob/master/LICENSE) 允许软件代码复用，但复制代码或实质部分时需保留许可和版权声明。角色素材与服务端模型另行判断。本轮未复制其运行代码或音频。

### 用户视频补充

[BV1U1PVeWEhp](https://www.bilibili.com/video/BV1U1PVeWEhp/) 为 Rcell 于 2025-02-26 发布的立体声 ASMR 模型展示。作者简介说明：使用 CosyVoice 的自回归阶段，结合自训练的立体声 Flow Matching 声学生成阶段，后者基于 Stable Audio 的相关结构。作者注明失败样本多、视频选取成功样本，并声明仅供学术研究、禁止商用。

这与 ryza-ai-revive 的客户端风格编排是两条技术路线，不能混为同一个开源实现。已成功读取视频标题及简介；播放器显示无法播放媒体，未实际听评。本轮未找到可确认对应视频的完整代码与权重发布，不把“计划开源”视为已经可下载、可部署。

## 2026-09-24 实验分支落地与实测

分支：`codex/whisper-tts-exploration`。本节为后续实现结果，前文关于“尚未实现/未实测”的描述仅代表调研阶段。

已接入 Qwen3 CustomVoice：工作台 Qwen3 参数中新增 `speaking_style`（normal / soft / whisper）和补充 `instruct`。默认 normal 不增加提示；其他风格与音色原有提示、用户补充指令按顺序拼接。超长句重合成时继续保留这些提示，再追加语速指令。同时修复多句重合成错误使用末句文本的问题。custom/clone 音色设置非默认风格或补充指令会明确报错，因为 Base 克隆接口不支持此参数。

这是本地独立实现，借鉴 Ryza 客户端的指令编排思路，没有复制上游代码、角色音色或素材。没有修改默认模型或默认风格。

### 如何使用

在工作台选择 Qwen3 与预设音色（例如 Vivian），将“说话风格（实验）”设为 `whisper`，可填补充指令，然后提交原有配音任务。`soft` 用于轻声对照，`normal` 使用原来的音色提示。新选项通过现有 ExecutionProfile 进入 TTS Runtime。

复现实测（项目根目录 PowerShell）：

```powershell
.runtimes/qwen_tts/Scripts/python.exe scripts/probe_whisper_tts.py
```

脚本强制离线，使用已安装的隔离运行时和本地 Qwen3-TTS-12Hz-1.7B-CustomVoice；缺少模型不会联网下载。默认写入 `output/whisper-exploration/`，重复运行会覆盖该目录同名样本，可用 `--output` 指定另一目录。三组使用相同文本、Vivian 音色、中文和随机种子 42。它在隔离解释器内直接调用本项目 TtsEngineRuntime → Registry → TTSEngine → Qwen3 模型；本次没有通过桌面点击提交完整视频配音任务。

### 真实 GPU 合成结果

文本：今天辛苦了。放松下来，慢慢呼吸，我会在这里陪着你。

| 风格 | 音频长度 | 合成耗时 | 峰值 CUDA 分配显存 | RMS |
| --- | ---: | ---: | ---: | ---: |
| normal | 9.44 秒 | 34.27 秒（含首次加载） | 4.17 GiB | 0.1267 |
| soft | 7.28 秒 | 14.76 秒 | 4.11 GiB | 0.0799 |
| whisper | 8.08 秒 | 15.69 秒 | 4.13 GiB | 0.0656 |

输出均为 24 kHz 单声道 WAV，非空、非静音且样本值有限；峰值均未超过 1。原始指标保存在 `output/whisper-exploration/results.json`。显存为 PyTorch allocated 峰值，不代表整机总占用。普通组包含冷启动，不应直接据此比较风格速度。运行时提示未找到 SoX，但本次三组生成均成功退出。

验证：`tests/test_whisper_tts.py`、`tests/test_provider_parameter_calibration.py`、`tests/test_runtime_isolation.py` 合计 **43 passed**；前端 `tsc -p desktop/tsconfig.json --noEmit --incremental false` 通过。测试覆盖运行时风格透传、默认行为、音色提示保留、克隆限制、无效风格，以及真实时间轴拼装逻辑中的逐句重合成（该项用模拟音频，不调用模型）。

### 结论与剩余边界

本项目可以实现指令驱动的耳语合成，已完成最小实验接入并产出真实音频。RMS 降低只说明输出能量变化，不能证明自然气声或 ASMR 质量；尚未主观听评，也未进行多音色、多语种、长文本稳定性验收。该能力继续标记为实验。

当前没有 HRTF、左右耳运动或原生立体声生成。完整配音仍受现有时间轴与混音增益策略影响，混音可能削弱轻声的响度差异；不能将本次短句试音等同于最终视频质量验收。后续应先试听这三组，再决定是否扩展双耳渲染及混音策略。
