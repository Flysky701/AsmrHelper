> 历史材料，归档于 2026-09-30。记录当时设计或验收，不作为当前配置及接入指南。TTS 当前入口：[统一 TTS 指南](../../guides/tts.md)。

# 音色实验室与多引擎 TTS 专项设计

状态：**历史审阅草案 v0.1，未实施；架构与实施范围已被 [v0.3 完整目标与引擎扩展契约](../../designs/voice-lab-v2-product-preview.md) 取代**
日期：2026-09-24
适用范围：当前工作区；包含尚未提交的耳语探索改动，实施前须重新核对主分支。

> 用户已明确不以旧实现兼容为约束。本文的旧 API 适配、双轨过渡及分阶段用户交付不再是执行方案；现状审计与风险记录仅供参考，以当前 v0.3 草案为准。

## 1. 本次需要审阅的决定

建议将音色实验室从 Qwen 音色生成入口，逐步扩展为“准备声音 → 配置引擎 → 试音对比 → 保存预设 → 正式配音”的工作区。复用已有任务、Provider、Artifact 和 Pipeline，不建立第二套执行系统。

优先审阅以下五项；文中均给出了建议默认方案，不需要逐个技术字段作决定。

| 决策 | 建议 | 影响 |
| --- | --- | --- |
| 第一版范围 | Fish 原生接入、双声音槽、可保存试音候选、用于正式任务；旧 Qwen 流程继续可用 | 先形成完整闭环，不一次重写所有引擎 |
| 声音组织方式 | 一个“声音预设”可以包含多个引擎绑定；第一版每引擎至多一个绑定 | 不先引入角色世界观、多人剧本领域 |
| ASMR 的含义 | 分开选择声音槽与发声风格，提供一键组合预设 | 耳语风格不必换声音，换 ASMR 声音不等于支持耳语指令 |
| 自动演绎 | 第二阶段加入；第一版手动控制和确定性规则 | 更容易定位效果与控制调用成本 |
| 试音与正式生产 | 共用合成解析器；正式任务固定配置快照 | 避免“实验室有效、正式配音失效” |

非目标：本轮不实现 HRTF、持续陪伴、角色动作、在线音色市场、Fish 云端声音创建、Step-Audio-EditX，也不替换现有对齐和混音策略。这些可作为独立后续扩展。

## 2. 当前源码事实与已有能力

以下为静态源码核查，不代表本轮做过运行验收。

| 现有部分 | 已具备 | 本次缺口 |
| --- | --- | --- |
| `desktop/src/pages/voice-lab/VoiceLab.tsx` | 音色列表、设计、克隆、参考候选选择和试听；提交后台任务 | 分组以 Qwen preset/design/clone 为主；缺少通用引擎绑定与持久试音对比 |
| `src/core/tts/voice_profile.py` | `VoiceProfile`、JSON 持久化、参考音频、prompt 缓存及 clone manifest | `engine/category/is_available` 具有 Qwen 语义，云端 ID 不能直接套用 |
| `src/app/services/voice_service.py` | `voice.design/clone/preview`、候选指纹、候选合格状态、确认文本、staging 与 Artifact 登记 | preview 使用 Qwen 语言归一化与 voice worker 路径；不是通用 Provider preview |
| `/voice/analyze-segments` | 同步分析，返回 analysis_id、candidate_id、来源和候选音频 | 长分析的取消与任务化是后续增量，第一版不承诺此接口可取消 |
| `src/core/engines/tts/registry.py` | edge、qwen3、voxcpm2、openai_compatible 注册 | 尚无 fish_audio Provider |
| `src/core/engines/tts/service.py` | StageProfile 分发、运行时路由、通用分段合成 | 引擎参数仍有分支；返回文件路径为主，需逐步增加元数据与控制映射 |
| `ExecutionProfileBuilder` / capability service | common/provider 参数 schema、默认值填充、校验 | 需要按模型/模式提供风格等能力和非静默降级规则 |
| Provider 命名连接 | `src/provider_profiles.py`、`task_connection_context.py` | 当前 TTS 连接投影偏向 external_tts；Fish 需带 provider 类型，不能误走 OpenAI 协议 |
| 连接恢复 | `src/recovery_connections.py` 有无密钥引用及变化校验 | 需验证并扩展到 Fish/实验室任务，不能宣称现有恢复已经覆盖新增类型 |
| Task V1 / Artifact / Pipeline | 后台任务、终态、重试归属、现有对齐混音输出 | 实验记录应聚合现有任务，不另造队列 |

旧 `VoiceProfile` 是引擎相关的底层音色资源，不立即改成通用角色。已有克隆片段质检、确认转录、文件指纹和任务 staging 必须保留。

参考：[Task Execution V1](../../contracts/task-execution-v1.md)、[Provider 契约](../../contracts/provider-v1.md)、[命名连接设计](../../designs/named-provider-profiles.md)。契约与新增源码有差异时，以实施前源码审计和契约补充为准。

## 3. 目标模块与责任

```text
音色实验室 / Workbench
  → VoiceService（预设、实验与任务入口）
  → SpeechRequestResolver（选择绑定、校验、固定快照）
  → TTS 编排（分段、可选演绎、调用、候选产物）
  → TtsEngineRuntime / Registry
      → Qwen 隔离 worker / VoxCPM runtime / Fish HTTP / 其他引擎
  → 标准音频产物
      → 实验室试听
      → 原有 Pipeline 对齐、混音、导出
```

- Settings 管理连接地址、凭据和模型访问配置；实验室选择连接名称，不保存第二份 API Key。
- 实验室管理声音及候选，Workbench 管理项目台词与正式生产；“用于工作台”只更新草稿，不自动创建收费任务。
- capability service 是能力规则唯一来源，前后端共用描述；服务端仍执行最终校验。
- 原始文本、渲染后的引擎文本、模型返回的音频分别保留，不互相覆盖。

## 4. 数据设计（全部为拟新增结构）

### 4.1 VoicePreset：用户层声音预设

| 字段 | 类型 / 含义 |
| --- | --- |
| id / revision / schema_version | UUID、单调递增修订号、结构版本 |
| name / description | 显示信息，不把名称作为关联键 |
| bindings | 引擎绑定列表 |
| default_binding_id | 显式默认绑定；不在失败时切换 |
| default_performance | 默认演绎配置或已固定的配置内容 |
| archived / created_at / updated_at | 归档与时间信息 |

角色身份不纳入本轮。未来一个角色可以引用 VoicePreset，不反向耦合。

### 4.2 VoiceBinding：某引擎上的声音实现

字段：`id, provider, model, connection_profile_id?, slots, provider_options`。

`slots.normal` 必须存在，`slots.soft/whisper` 可选。每个槽是带类型的 VoiceSource：

| source.kind | 字段 | 使用对象 |
| --- | --- | --- |
| legacy_qwen_profile | profile_id | 引用现有 A/B/C 音色，避免复制 prompt |
| builtin_voice | voice_id | Edge、模型预设 speaker 等 |
| hosted_voice | reference_id | Fish 等服务端音色 |
| reference_audio | reference_asset_id | VoxCPM 等支持参考音频的引擎 |

这些类型不能任意跨引擎使用。Qwen prompt 缓存不可传给 VoxCPM；Fish reference_id 不等于本地音频。第一版 UI 先支持 Qwen 兼容与 Fish 绑定，其余绑定逐个接线验收。

声音槽缺失时拒绝提交并指出缺项。用户可以明确改选普通槽继续测试耳语指令；禁止默认偷偷回退。

### 4.3 ReferenceAsset：可复用参考素材

字段：`id, source_fingerprint, managed_audio_path, audio_hash, transcript, language, style_label, sample_rate, channels, duration, provenance, preprocessing_version`。

从已有 analysis_id/candidate_id 确认后，将选中片段提升为持久素材；不把临时分析目录当永久引用。`provenance` 保留原始来源、切片时间和确认转录记录。旧素材不强制复制；采用时检查存在性并记录摘要。

参考音频换转录、重新裁剪或预处理均产生新修订。Qwen prompt 缓存绑定模型/运行时/预处理版本，不能仅按声音名称复用。耳语质检模式作为后续增量，不直接全局降低现有 RMS 门槛。

### 4.4 PerformanceSpec / SegmentPlan：通用演绎

第一版字段：`delivery(normal|soft|whisper), emotion?, pace?, pause_after_ms, policy(strict|explicit_fallback)`。音色槽由 `voice_slot` 独立指定。

第二阶段增加逐句 `segment_id, source_text_hash, cues[{offset, kind, value}], previous_emotion`。以 Unicode code point 作为持久偏移标准；前端 UTF-16 在边界转换并测试 emoji，不能照搬 Dart 偏移直接切 Python 字符串。

不定义通用“0–100 耳语强度”，也不把 temperature 当通用情绪强度。引擎无法表达的字段在提交前列为 unsupported，strict 拒绝；explicit_fallback 必须包含用户已选择的替代方式，并保留原始意图与实际映射。

### 4.5 VoiceExperiment / Candidate：实验与候选

- Experiment：`id, name, text, language, source_hash, candidate_ids, selected_candidate_id?, created_at`。
- Candidate：`id, experiment_id, task_id, preset_id/revision?, resolved_snapshot, artifact_ids, metrics, warnings, created_at`。
- 每次“重新生成”产生新 candidate 和 Task；不覆盖旧音频。任务状态从 Task V1 获取，不另存一套可变执行状态。
- 选中候选只代表实验选择，不自动把该句音频用于所有正式台词。正式 Pipeline 使用其配置；原音频替换只在未来显式“采用此段”功能中提供。
- `metrics` 包含实际时长、采样率、声道、生成耗时、缓存命中、削波提示；不伪造“耳语质量分”。

### 4.6 持久化与删除

建议新建 `config/voice_library.json`（schema_version=1），由一个 repository 负责预设/素材元数据、锁、原子替换和 revision 冲突；保留原 `voice_profiles.json`。这是通用配置目录，不在 Qwen profile 文件中增加无法反序列化的字段。

实验元数据放 `output/voice-lab/<experiment_id>/manifest.json`；音频仍由 Task Artifact 服务管理，manifest 引用 artifact_id。不要让两个服务各自清理同一文件。

归档预设不删除任务快照。素材被预设或任务引用时不可物理清除；第一版仅显式清理未引用产物，不自动回收候选。并发更新携带 expected_revision，冲突返回 409，不覆盖另一窗口修改。

## 5. 用户流程与页面分区

保留“音色实验室”入口，渐进拆分现有大组件：

1. **左侧声音库**：名称搜索、引擎过滤、可用性说明；旧 Qwen 音色保留原 ID，作为兼容项显示。
2. **声音配置页签**：引擎绑定、连接名称、模型、普通/轻声/耳语槽；Fish 的槽显示 Voice ID，本地引擎显示参考素材。
3. **参考素材页签**：复用现有分析、候选试听、确认转录与克隆界面；不适用的引擎隐藏入口并解释能力。
4. **试音页签**：公共测试文本/语言、声音槽、可用的演绎控制、引擎高级参数；“生成候选”提交后台任务，页面内显示进度并提供任务中心链接，不强制跳走。
5. **候选对比区**：至少支持两项切换、原始播放/等响度试听、参数差异、设为选中；等响度仅改变试听，不覆盖原文件，首版不能以增大音量冒充品质改善。
6. **应用操作**：“保存预设”“用于工作台”。有未保存修改时明确使用当前快照还是已保存修订，不隐式保存。

典型 Fish 流程：设置页新建 Fish 连接 → 实验室添加声音绑定 → 填普通及耳语 Voice ID → 输入短句 → 比较两份候选 → 保存 → 用于 Workbench → 提交正式任务。

典型 Qwen 流程：原有候选分析/克隆 → 生成旧 profile → 兼容绑定立即可试音 → 可保存为通用预设。不能要求旧用户重新克隆。

切换引擎时保留公共文本，专属字段按绑定独立保存；清空无效控件的显示不等于丢弃已保存配置。生成按钮说明是否云端调用、候选数量；第一版不做一键全模型付费批测。

## 6. 能力描述与请求解析

在现有 descriptor 的 supports/schema 上添加版本化 `voice_controls`，不是再维护一份前端引擎表：

```json
{
  "version": 1,
  "source_kinds": ["hosted_voice"],
  "controls": {
    "delivery": {"transport": "text_tags", "values": ["normal", "soft", "whisper"], "quality": "unverified"},
    "pause_after_ms": {"transport": "postprocess"}
  }
}
```

支持传参与实测效果分开：可传 whisper 不代表保证耳语音质。能力必须能随 model/mode 收窄；静态 unknown 不等同 supported。无新描述的旧引擎保留原有控件，禁止自动推定新能力。

解析顺序：绑定默认值 → 演绎预设 → 本次明确 override → 校验 → 引擎渲染。snapshot 保存来源修订、完整生效非敏感参数、renderer_version、模型标识、输入摘要和实际标签文本。字段冲突按明确顺序处理，不让 voice preset 和 provider_options 各自覆盖对方。

`pause_after_ms` 在通用片段组装层加一次，不再同时转成引擎停顿标签。没有时间轴的试音允许加尾停顿；有字幕时间轴的正式任务遵循原有对齐策略，超出可用间隙时提示冲突，不移动字幕或双重拉伸。实验室生成的原始时长和正式对齐后的时长分别展示。

## 7. Fish 原生适配

新增 provider ID：`fish_audio`，不冒充 `openai_compatible`。建议文件：

- `src/core/engines/tts/fish_audio.py`：HTTP 合成、错误映射、响应音频检测。
- `src/core/engines/tts/fish_rendering.py`：Fish 文本标签渲染、密度与模型兼容。
- 通用 planner 放通用领域模块；不让 FishClient 调用 LLM 或维护角色状态。

第一版只支持现有 hosted Voice ID，模型由连接/绑定明确选择；不复制浏览器 API Key，不硬编码作者音色为默认，不自动从免费模型升级收费模型。

请求必须依据实施时验证的 Fish API schema 构造。AgentAtelierR 的 `s2-pro`、temperature、prosody、normalize 等仅作实验配方；`s2.1-pro-free` 与 `s2-pro` 不假定一致。无法确认支持的高级字段暂不发送。模型映射和标签规则纳入 renderer_version。

情绪与 temperature 分开；可提供命名实验预设，但标明其来源与未验证状态。ASMR 声音槽、delivery=whisper、emotion 三者可单独对比。

响应先写任务私有临时文件，检查状态码/内容类型/实际可解码性，再登记 Artifact。服务端 MP3 不能仅改后缀当 WAV；按下游需要转换并保留原始响应音频，转换耗时单独记录。

超时、429、鉴权失败、音色不可访问、无效文本、音频解码失败分别返回可操作错误。遵守 Retry-After 并限制重试次数；发送后超时可能已计费，结果不明时不无条件重复合成，提示用户显式重提。

## 8. API 与任务接口草案

以下路径均相对 `/api/v1`，并非已实现接口。新通用集合使用 presets，避免与旧 Qwen profiles 冲突。

| 接口 | 行为 |
| --- | --- |
| GET/POST `/voice/presets` | 列表、新建；POST 返回 201 |
| GET/PATCH `/voice/presets/{id}` | 详情、带 expected_revision 更新；归档也是 PATCH |
| POST `/voice/references` | 从有效 analysis/candidate 提升持久参考，或引用经校验的既有素材 |
| POST `/voice/experiments` | 创建文本实验，返回 201 |
| GET `/voice/experiments/{id}` | 候选列表、配置、Artifact 引用 |
| POST `/voice/experiments/{id}/candidates` | 一次一个候选；返回 201，包含 candidate_id 与标准 TaskStatus |
| PATCH `/voice/experiments/{id}` | 修改选中候选/实验显示名称；不得改写已有候选输入 |

候选提交示例（字段最终需落 DTO/schema）：

```json
{
  "preset_id": "voice-uuid",
  "expected_revision": 3,
  "binding_id": "binding-uuid",
  "voice_slot": "whisper",
  "performance": {"delivery": "whisper", "pause_after_ms": 0, "policy": "strict"},
  "provider_overrides": {"temperature": 0.62},
  "cache_mode": "regenerate",
  "client_request_id": "submission-uuid"
}
```

实验拥有固定文本；改文本创建新实验或明确复制，不影响历史。client_request_id 只防重复提交，不等于音频内容缓存。

Task 继续使用 `voice.preview`，execution_profile 增加版本化 resolved_request；执行器区分旧 profile_id 请求与新 schema_version 请求。旧 `/voice/profiles/{id}/preview` 保留兼容适配，不改其响应结构。

设计/克隆继续沿用原 task_type 和 worker，不能因为新增 Fish 破坏旧执行路径。任务状态、取消、重试使用现有 Task API。实验组只聚合任务，无独立执行线程。

正式 Pipeline 保留 StageProfile v1 外层；在 TTS 的 schema 允许扩展中接收声音预设选择，提交时解析成固定生效参数并保存版本化非敏感 snapshot。试音与 Pipeline 必须调用同一个 resolver/rendering 路径，不能在 Workbench 手工拼一份近似参数。修改相关契约与 schema 后才能发送新字段。

## 9. 执行、缓存、取消及凭据

- 复用 TaskDispatcher；第一版候选单次提交、本地 GPU 继续既有串行资源约束，Fish 默认每连接并发 1。不新增全局调度平台。
- 合成结果统一元数据：原始/转换后 artifact_id、sample_rate、channels、duration、warnings、elapsed。为旧返回路径的引擎加适配，不一次改掉全部 synthesize 签名。
- 缓存键包含文本、语言、provider/model、非敏感连接身份、声音来源内容摘要、参数、实际演绎文本、renderer/preprocess 版本、可用 seed。云模型版本不可固定时注明不可保证重现。
- “重新生成”绕过内容缓存；“复用已有结果”明确显示缓存命中。不同任务引用同一内容时由 Artifact 管理显式复用/副本归属，不伪造原任务所有权。
- 取消遵守 Task V1：请求取消不等于远端停止计费；请求返回后检查取消，不登记成功候选，不继续后续片段。迟到音频仅清理本任务临时文件。
- 重试创建新 Task 与新 candidate，链接旧任务/候选；已完成候选不覆盖。重启后遵守已有恢复策略，不默认自动重发云请求。
- 密钥留在既有连接配置/私有任务上下文，manifest、日志、StageProfile 不含密钥。扩展命名连接的 provider 类型和恢复投影，确保 Fish 不能落入 OpenAI URL 拼装。
- 同进程固定连接副本；跨进程重提核验原非敏感配置与凭据引用，无法证明一致时明确失败并允许用户以当前连接新建任务。不得回落当前全局活动连接。

## 10. 自动演绎的第二阶段

通用 planner 输入原台词与明确上下文，只返回语义 cue 和位置；输出经 schema、偏移、原文 hash、数量、标签枚举校验后再进入引擎 renderer。Fish renderer 才生成方括号标签。

LLM 不改台词、不更换人物音色、不控制混音；按源文本重建结果。计划与实际引擎文本随 candidate 保存。同配置重试默认复用已通过校验的计划；“重新规划”是显式新候选。

失败默认停止自动演绎候选，并允许选择规则模式重提；若用户已选允许规则回退，则记录 warning 和实际采用的计划。规划使用独立辅助用途设置，不悄悄覆盖现有翻译提示词。

## 11. 迁移与兼容

1. 不改旧 A/B/C ID，不改写原 voice_profiles.json；先通过只读兼容视图映射旧 profiles，用户保存通用预设时才创建新对象。
2. 旧 Qwen preview、design、clone 以及 Workbench voice_profile_id 调用继续可用；新旧请求同时覆盖回归测试。
3. 旧外部 TTS 命名连接默认仍是 openai_compatible，不按域名猜测为 Fish。
4. 新配置写入前生成可恢复备份，repository 采用临时文件+原子替换；未知 schema_version 拒绝写入，不能覆盖成空列表。
5. 回退旧版本时保留新 library/实验文件但不要求旧版本读取；旧音色文件仍可读。不得把新字段写进旧 dataclass 不能接收的 JSON。
6. 通用 presets 使用软归档；旧删除接口的行为不在此阶段偷偷改变，但已迁移引用的资源删除需要被引用检查。

## 12. 文件级实施拆分

| 区域 | 复用/修改 | 拟新增 |
| --- | --- | --- |
| 声音领域 | `src/core/tts/voice_profile.py` 兼容适配 | `src/core/voices/` 的模型、repository、resolver；具体目录在实施时确认 |
| 引擎 | `src/core/engines/tts/{registry,service}.py` | Fish client 与 renderer |
| 应用 | `voice_service.py`、capability service、execution_profile_builder、Pipeline 提交解析 | 实验聚合服务，避免继续扩大 VoiceService |
| 连接 | provider_profiles、task_connection_context、recovery_connections、settings service | Fish 类型校验与投影 |
| HTTP | voice/tts DTO、schema、routes | presets/references/experiments 契约 |
| 前端 | VoiceLab、voiceApi、共享类型、Workbench、Settings、现有任务/播放器 store | PresetEditor、EngineBindingEditor、ReferencePanel、ExperimentPanel、CandidateCompare |
| 文档 | provider/task/schema/compatibility 契约与能力事实清单 | Fish provider 文档和实际验收记录 |

现有 `MixPreview` 及其他并行改动不在本轮重写；需要集成时以其公开接口为边界。

## 13. 分阶段交付与验收

### P0：审阅与契约收敛

确认第 1 节五项决定；逐项落实 schema、连接类型、旧 Profile 兼容策略。产出字段契约及第一批任务清单，不开展大规模 UI 重构。

### P1：最小跨引擎闭环

新增 Fish Provider、VoicePreset/Binding、配置解析快照、通用 preview 分支、基础候选历史；实验室可保存 Fish 预设并用于 Workbench 的完整 Pipeline。保留旧 Qwen 页面流程和任务入口。

验收：同一 Fish 配置在试音与正式合成阶段发送相同语义参数；云端音频能进入现有对齐混音；旧 Qwen 克隆与试音不回归；不可用声音/连接在明确阶段失败；任务期间修改连接或预设不影响已提交任务。

### P2：实验室工作流完整化

完成参考素材持久化、普通/轻声/耳语槽、确定性演绎规则、两候选参数差异及等响度试听；VoxCPM 参考绑定接线；缓存/重新生成语义落地。

验收：引用素材不因分析缓存清理失效；跨引擎能力受限项明确；重新生成有新产物；候选可选定并把配置送入工作台；对齐超时长/停顿冲突可见。

### P3：自动规划与局部重生成

加入通用 LLM 演绎计划、逐句编辑和正式任务分段候选采用。后者需另补片段版本与时间轴契约，不在 P1 声称已经支持。根据实际瓶颈再加入预生成与并发调优。

验收：原文逐字符保持；错误标签/偏移被拦截；取消后没有后续句请求；单句重生成不重做未修改片段；采用新片段后重新计算受影响的对齐结果。

## 14. 验证矩阵

| 层面 | 必测场景 |
| --- | --- |
| 兼容 | A/B/C profile、旧 preview schema、Qwen design/clone、旧 Workbench 任务 |
| 配置 | preset revision 冲突、缺失槽、连接 provider 不匹配、unsupported 字段、严格/显式回退 |
| Fish 模拟 | 模型 header、reference_id、标签渲染、401/429/超时/非音频响应、格式转换 |
| 一致性 | 试音/正式请求映射一致；修改连接不污染运行任务；重新生成绕过缓存 |
| 资源 | 素材摘要变化、临时分析过期、引用资源清理、候选文件隔离 |
| 生命周期 | 重复提交、取消中途响应、失败重提新 Task、进程重启后的显式恢复 |
| 前端 | 保存/未保存状态、刷新后实验恢复、两候选试听、用于工作台、能力控件切换 |
| 真实声音 | 固定短句与音色，重复生成；人工记录漏字、气声、音色保持与等待时间 |

日常测试使用模拟 HTTP 和现有回归；真实 Fish 调用单独标记并受当前授权/额度约束，不进入自动测试。质量验收与接口成功分开，不能凭 HTTP 200 宣称 ASMR 达标。

## 15. 证据与未解决问题

- [Ryza 工程核查](../../designs/ryza-engineering-review.md)：AgentAtelierR 为专用音色+演绎规划，触碰部分使用本地素材；不能把视频听感全归因于 TTS。
- [Fish 实测](../../designs/fish-official-probe.md)：当前已验证短句链路，用户反馈耳语标签差异不明显；尚未复现上游具体音色/模型。
- 上游代码许可不同：ryza-ai-revive 有 MIT；AgentAtelierR 本次未见根 LICENSE，参考工程思想独立实现，不直接搬运声音素材或源码。
- 待实施验证：Fish 当前模型/字段能力；命名连接对新 provider 的恢复覆盖；试音原始音频与正式对齐后的听感差异。
- 未给固定工期：P1 涉及配置、任务和 Pipeline 三个边界，应在契约确认后按独立可合并切片估算。
