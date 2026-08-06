# AsmrHelper 当前源码基线

日期：2026-07-23

## 1. 本文定位

本文是当前 DOCS 的事实基线。

架构、环境、文档定位和完整问题清单见 [当前架构与文档审计](current-architecture-and-doc-audit-2026-07-23.md)。本文只记录可由当前源码与验证直接支撑的事实。

后续判断项目进度时，优先级如下：

1. 当前 `git log`、`git status`、`src/` 与 `desktop/` 源码结构。
2. 当前可运行的验证命令。
3. 活跃契约文档。
4. 归档计划和旧 roadmap 只能作为历史背景，不能作为当前状态依据。

## 2. 当前 Git 状态

当前分支：

```text
refactor/re-design
```

当前 HEAD：

```text
f7c6b52 feat: 补齐 TaskStatus 横向字段（stage / timestamps / error / artifact_set_id）
```

近期对状态判断有直接影响的提交：

| commit | 结论 |
|---|---|
| `74fa181` | 已移除旧 GUI、deprecated API 和 legacy pipeline |
| `a190cac` | Phase 2A 收尾与能力描述符扩展已推进 |
| `6326d6b` | 桌面端任务状态已与后端 `TaskStatus` 对齐 |
| `5e61d14` | 桌面端页面已完成一轮重构 |
| `605d825` | pipeline 预设、TTS voice list 和 preset 配置已接入 |
| `b494ad6` | VoxCPM2 TTS 引擎已接入 |
| `c4271d7` | 模型安装支持按需安装 Python 依赖 |
| `3bd5c4a` | 完成 Workbench、TaskCenter、导航与样式的一轮桌面 UI 重设计；LLM registry 与能力描述符继续收束；重组 docs |
| `f7c6b52` | TaskStatus 已补齐阶段、时间线、结构化错误和产物集合关联字段 |

仓库最后一次提交日期为 2026-05-27。本次恢复工作已在工作区更新 UV 锁文件、安装/启动脚本和 Vite 配置；这些未提交变动属于当前环境收束工作。因此后续执行必须区分：

- `HEAD` 已提交事实。
- 当前工作区事实。
- DOCS 正在更新中的事实。

## 3. 当前源码事实

### 已不存在的旧路径

以下路径在当前源码树中已经不存在，不能再作为当前待迁移对象描述：

```text
src/gui/
src/core/pipeline/
src/core/script_to_subtitle/
src/core/subtitle_generator.py
src/core/script_processor.py
```

如果活跃文档仍提到这些路径，应改成历史迁移背景或归档内容。

### 当前 pipeline 主路径

当前 pipeline 主路径已经在：

```text
src/core/orchestration/pipeline/
```

关键文件：

| 文件 | 当前职责 |
|---|---|
| `models.py` | `PipelineExecutionContext`、`PipelineExecutionPlan`、stage binding |
| `planner.py` | 从 execution profile 生成执行计划 |
| `executor.py` | 直接调用 separator / ASR / LLM / TTS / mixer runtime |
| `result_mapper.py` | 结果与 artifact 语义映射 |

因此，当前不能再描述为“pipeline 仍通过 LegacyPipelineOrchestrator 驱动旧 `src/core/pipeline`”。更准确的说法是：

> pipeline 主执行器已经迁到 `core/orchestration/pipeline`，API 执行已移出请求线程；StageProfile、终态历史持久化、Provider 设置、TaskResult/Artifact 和 RuntimeEvent 契约已经落地。

### 当前任务系统

当前任务系统已经存在：

```text
src/core/tasks/
src/app/services/task_service.py
src/api/http/routes/tasks.py
```

当前状态：

- `TaskSpec`、`TaskStatus`、`TaskRegistry` 已存在。
- `TaskService` 已经委托 `core.tasks.TaskRegistry`。
- `TaskStatus` 已包含显式 `stage`、结构化 `error`、时间字段和 `artifact_set_id`。
- Pipeline 支持后台接管、协作取消；重试会创建新任务，不覆盖原任务事实。
- SQLite 保存终态 TaskSpec、TaskStatus 和 Artifact 索引；默认位置为 `%LOCALAPPDATA%\AsmrHelper\state.sqlite3`，可通过 `ASMR_HELPER_STATE_DB` 覆盖。
- 重启后只加载终态历史，删除未完成任务及其 Artifact 索引；历史任务只读，重新执行需从 Workbench 提交新任务。
- 运行调度基于进程内线程；受性能和个位数线程规模限制，当前明确不建设可恢复的持久化执行队列。

### 当前桌面端状态

当前桌面端在：

```text
desktop/
```

当前状态：

- `Workbench` 已能选择文件、配置参数，并通过 `POST /pipeline-runs` 一次创建和启动后台任务。
- Workbench 直接提交嵌套 `input/output/execution_profile`，每个阶段使用统一 `StageProfile`。
- `TaskCenter` 已消费后端显式阶段，启动时载入历史任务，并按需查询统一 TaskResult；主产物与预览能力均由 Artifact 契约声明。
- 当前会话任务支持状态轮询、协作取消和新任务重试；重启后的历史任务只用于查看。
- `EnginesResources` 已接入模型安装状态、异步安装和进度轮询。
- 模型状态已区分权重/包安装状态与当前进程可执行性；桌面端会显示明确的依赖、系统工具或 GPU 缺失原因。
- 桌面端已经不是空壳，也不是未接后端阶段。

当前约束：

- 执行队列仍只存在于进程内，APP 重启后按约定删除未完成执行；低并发产品范围内不建设独立调度器。

### 当前引擎与资源状态

当前源码已经存在：

```text
src/core/engines/asr/
src/core/engines/llm/
src/core/engines/tts/
src/core/engines/separator/
src/core/resources/
src/core/runtime/
```

当前状态：

- ASR、LLM、TTS、separator registry/runtime 已经是主路径的一部分。
- `ModelManager` 仍保留在 `src/core/model_manager.py`，但已是 deprecated 兼容层，不应再描述为新代码默认入口。
- TTS 侧仍存在 Qwen3 相关 manager 与 voice 扩展能力，属于扩展能力兼容与逐步收束对象。

### 当前字幕与文本状态

当前新主路径已经在：

```text
src/core/subtitles/
```

已经包含：

```text
cleaner.py
exporter.py
generator.py
loader.py
normalizer.py
parser.py
script_processor.py
script_to_subtitle.py
script_tool.py
service.py
text_utils.py
```

不能再说 `script_to_subtitle / subtitle_generator / script_processor` 尚未迁入 `core/subtitles`。更准确的说法是：

> 字幕和脚本文本能力已经迁入 `core/subtitles`，剩余问题是部分 app service 或兼容入口仍可能引用旧路径或旧语义。

2026-07-23 已完成残留引用修复：`src/app/services/script_subtitle_service.py` 现在懒加载 `src.core.subtitles.script_to_subtitle.ScriptToSubtitlePipeline`，并有真实 runtime 导入路径回归测试保护。旧路径不存在仍是事实，但不会再被该应用服务调用。

## 4. 当前验证结果

2026-07-28 最新验证：

```text
.venv\Scripts\python.exe -m compileall -q src
```

结果：通过。

```text
.venv\Scripts\python.exe -m pytest -q
```

结果：`205 passed`。

启动环境使用 Python 3.12.13，`scripts/verify_env.py` 已确认 FastAPI、Uvicorn、HTTP API（88 routes）可用。

本地 ASR / 分离 / 混音依赖已移入 `audio` 可选组，避免其阻塞 API 与桌面端首次启动；当前环境已通过 `audio` 安装档安装 CPU PyTorch、Demucs、Faster-Whisper 和 imageio-ffmpeg，并下载 Faster-Whisper Base 权重。最小真实链路（本地音频 → ASR → export）已完成，任务状态为 `completed`。CUDA 仅作为后续性能加速选项，不再是首次本地执行的前置条件。

桌面端已验证：使用 `E:\Dependencies\nodejs` 的 Node v24.18.0、npm v11.16.0 执行 `npm ci` 与 `npm run build` 通过；Rust 1.97.1/Cargo 1.97.1 已安装，`npm run tauri -- build` 通过并生成 `desktop/src-tauri/target/release/asmr-helper.exe`。该程序已启动，后端 `/health` 返回正常。

2026-07-26 完成桌面 P0 可用性修复：API client 支持空响应并统一错误解析；Tauri 原生文件对话框权限已显式配置；文件选择器按音频、字幕、台本和目录分类；TaskCenter、SubtitleWorkshop 与 VoiceLab 的音频入口接入统一播放器；当前后端未支持的预设 CRUD 和音色修改按钮已明确禁用。验证结果为 `npm run build` 通过、Tauri release build 通过、`tests/test_http_api.py` 为 `38 passed`，release 程序已实机确认能够打开带“音频”过滤器的原生文件对话框。

2026-07-26 完成桌面 P1 能力与运行条件接入：Workbench 从 `/capabilities` 加载 ASR、TTS、LLM、separator 的 provider/model；`/runtime/check-task-readiness` 不再只检查工作目录，而是按启用阶段验证 capability、支持模型、模型可执行状态和 provider 凭据，响应包含结构化 `issues`。客户端在创建本地任务和提交后端任务前执行该检查，并按问题类型引导到设置页或引擎与资源页。当前默认组合为 `demucs + faster-whisper-base + DeepSeek + Edge TTS`。

2026-07-28 完成交叉检查修复：字幕翻译和双语字幕产物登记的 `Path` 运行错误已修复并覆盖真实分支；Pipeline 在任务创建和 `prepare` 阶段执行后端权威 readiness；默认分离组合统一为 `provider=demucs, model=htdemucs`；readiness 已覆盖 Edge TTS Python 依赖、实际 FFmpeg 可执行文件和逐文件媒体解码探测；DeepSeek 默认模型以 LLM Registry 为唯一运行时事实源，当前为 `deepseek-chat`。随后清理历史测试与执行配置：CLI/batch 平铺参数在 PipelineService 边界统一归一化为 StageProfile V1，planner 不再接受旧 profile，测试中的假 provider 与旧兼容断言已修正，同时保留旧 HTTP 路由和旧模块路径的负向架构守卫。全量测试 `181 passed`，桌面生产构建通过，Ruff 的 `F821` 和 `F601` 已清零。

2026-07-30 完成默认单文件主链路手动验收：真实音频使用 `demucs/htdemucs → faster-whisper-base → DeepSeek → Edge TTS → FFmpeg` 完整执行成功，任务正常完成并生成最终产物。该结论只覆盖当前默认组合的单文件路径；批量任务、异常恢复和其他 Provider 仍需分别验收。

2026-07-30 完成 P1.5 第一批参数与音色联动：Workbench 直接消费 CapabilityOption，动态呈现当前 ASR、LLM、TTS Provider 的基础类型参数，并按契约把参数写入 `options` 或 `provider_options`；TTS 声线改为读取 `/tts/engines/{engine_id}/voices`，Qwen3 音色档案只显示当前可用且引擎匹配的 profile，`voice_profile_id` 已归入 Provider 私有参数。全量测试 `182 passed`，桌面生产构建通过。

2026-07-30 固化并精简 Provider / Model 接入流程：已有 Provider 增加普通模型只需登记能力、资源映射和最小验证；新增 Provider 按“确认上游事实、完成 Server、真实验收”三步处理，不要求逐 Gate 文档或提交。`config/models.yaml` 使用 `capability_models` 显式映射运行模型 ID，readiness 不再依赖单候选隐式回退；自动守卫只检查模型目录、能力目录、默认模型和参数 schema 等运行关键一致性。当时全量测试 `187 passed`。

2026-07-30 完成第一批 Server 参数校准：按当前锁定的 `faster-whisper==1.2.1` 与 `edge-tts==7.2.8` 核对上游接口。Faster-Whisper 改用上游正向 `vad_filter`，`beam_size`、`initial_prompt` 和 `no_speech_threshold` 已从 Capability 传到实际 `transcribe` 调用，不再硬编码日语提示词；Edge TTS 的公共 `speed` 倍率已转换为上游 `rate` 百分比。ExecutionProfileBuilder 和 Pipeline readiness 会在运行前检查公开参数的名称、类型和范围。参数校准后的默认真实音频主链路已由 `pipeline-5` 完整执行通过。

2026-07-31 修复 Edge TTS 瞬时连接失败：`pipeline-6` 在 TTS 阶段发生 WebSocket 连接超时，相同参数的 `pipeline-7` 重试成功，确认不是 voice/speed 参数错误。Edge 句子合成改为最多 4 个并发连接，单句瞬时网络错误最多尝试 3 次，并支持 Capability 中的可选 `proxy`。当前开发机通过 `http://127.0.0.1:7890` 完成项目级真实 Edge TTS → WAV 探测；修复重启后，用户已完成 APP 侧验证。全量测试 `199 passed`。

2026-08-01 模型安装链路继续收敛：Fun-ASR、Qwen3-ASR 和 VoxCPM2 已绑定项目模型目录，Kokoro 可通过通用时间线适配进入 Pipeline；Workbench 会提交明确的翻译模型和 TTS 默认模型。客户端异步安装已兼容纯 Python 包策略，能按模型默认模式安装或修复缺失的 Python 依赖；UV 明确向后端当前解释器安装，下载子进程输出不会再阻塞长任务。模型列表会把云端模型缺省的安装策略归一化为空字符串，避免资源页请求返回 500。大模型下载改为后端串行和单文件执行并延长读取超时；连接中断会重启下载进程，从 HuggingFace `.incomplete` 文件自动续传，最终 subprocess 错误会进入任务。模型文件按声明路径精确校验，避免子目录同名权重造成假完成。当前全量测试 `214 passed`，桌面生产构建通过；除默认组合外的 Provider 仍需按 [多引擎支持现状](multi-engine-status.md) 分别安装和真实验收，环境隔离后续按 [运行环境隔离 TODO](runtime-environment-isolation-todo.md) 按需实施。

2026-08-01 完成运行环境隔离第一阶段与 Qwen3 CustomVoice 验收：`runtime_profile` 已定义 `main`、`qwen_asr`、`qwen_tts`，只有用户实际选择的 Qwen3-TTS 创建 `.runtimes/qwen_tts`；模型资产继续共享 `models/`。模型安装、状态和 CUDA 检查面向目标解释器，TTS Runtime Router 通过短生命周期 Worker 执行 Qwen3，结构化错误及完整 Worker traceback 写入后端日志。当前隔离环境为 Torch `2.10.0+cu126`、`transformers 4.57.3`、NumPy `2.4.6`，正式 TTS API 已生成有效 24 kHz 非静音 WAV，重复执行后无残留 Qwen Worker。全量测试 `219 passed`，桌面生产构建与 Ruff `F821/F601` 通过。随后用户完成 `pipeline-8` 单文件手动验收，任务由 Workbench 提交并在 `export` 阶段正常完成，Qwen3 CustomVoice 的真实 Pipeline 主链路已通过。

2026-08-03 完成后端 P0 批量与异常恢复验收：顺序批量任务以确定性服务层故障注入验证“成功 → TTS 失败 → 成功”，中间失败不阻塞后续任务；三个任务分别保留 `completed/failed/completed` 状态，失败阶段为 `tts`，成功产物严格归属于各自 task_id。Edge TTS 瞬时连接失败重试、模型下载中断后保留 partial 文件并重试、隔离 Worker 无响应退出及交换文件清理、任务取消后以新 task_id 重提并生成新产物均已覆盖。批处理创建改走后端权威 readiness，失败汇总保留原输入路径；`verify_env.py` 可从项目外目录直接执行。全量测试 `226 passed`，桌面生产构建、compileall、Ruff `F821/F601` 均通过。该结论验证后端编排与恢复语义；Edge 和下载故障采用确定性模拟，不宣称真实外部网络在任意故障下均可恢复。

当前边界必须保持明确：`POST /pipeline/batch` 仍是等待全部项目结束后返回的同步聚合接口，每个输入会创建独立 Pipeline task，但尚无独立 batch task_id、批量状态查询或 HTTP 批量取消入口；桌面端仅有 API 封装，当前页面未消费该接口。取消后重提验收针对单任务 `PipelineTaskOrchestrator`；Worker 异常退出会使当前任务明确失败并清理交换文件，不会自动重启 Worker，恢复方式是重提新任务。

2026-08-04 已完成 [后端能力事实清单](backend-capability-baseline.md)：按“已实现、环境可执行、真实验收、已接线、受限”区分当前能力，并明确批量、历史任务、运行环境、VoiceLab、兼容层和 GUI 可依赖边界。后续 GUI 整理以该清单和当前源码为准，不再从路由存在或设计稿推断能力已完成。

2026-08-07 启动链路已补齐隐藏后端、持久日志、真实 PID 清理和 installed/dev/release 三种模式。Qwen3-ASR 0.6B 已通过直接 HTTP API；随后使用固定非敏感合成句完成 `Qwen3-ASR 0.6B → DeepSeek → Qwen3 CustomVoice` Pipeline，得到混音、双语字幕、TTS WAV 和 ASR 文本四类有效 Artifact，且无 Worker 残留。验收中发现并修复 Edge TTS 的 MP3 同路径转码错误。全量自动化更新为 `243 passed`，桌面生产构建、`compileall` 和 Ruff `F821/F601` 通过；GUI 可见交互仍需 Computer Use 恢复后单独验收。最新逐项边界以 [后端能力事实清单](backend-capability-baseline.md) 为准。

同日 Voice Design、Clone、Preview 和 Analyze 完成正式 API 真实验收：设计与克隆档案可用，参考音频、prompt cache 和试听 WAV 均有效且按任务登记 Artifact，测试档案经正式接口删除；片段分析返回有效候选与警告。分析链路已从旧 ASR 识别器迁到统一 ASR Runtime，修复 `faster-whisper-base` 资源 ID 被底层误当模型尺寸的问题。

VoiceLab 随后按真实契约完成对齐：设计档案使用 `custom` 分类，设计/克隆完成后立即加载详情；片段分析提交 `subtitle_path/audio_language` 并显示后端 `score/recommended_indices/warnings`；预设音色不再提供无效删除按钮，GPU 状态也不再硬编码为“可用”。桌面生产构建通过。

主 `.venv` 与 Qwen TTS、Qwen ASR、FunASR 三个隔离运行时已统一迁移到项目内 UV Python 3.12.13，不再继承 AetherSwap Conda 或用户目录 UV Python。主环境与三个隔离环境的依赖一致性检查均通过；重建后 Qwen3-ASR 0.6B、Qwen3 CustomVoice 和默认正式 Pipeline 均完成真实推理。FunASR 只确认运行时可导入，模型资产缺失，仍应显示为未安装。当前自动化基线为 `245 passed`，桌面生产构建、环境检查、`compileall` 与 Ruff `F821/F601` 均通过；旧环境以 `.runtimes/*-backup-*` 保留，尚未删除。

TaskCenter 随后完成契约收口：重试不再原地替换旧任务，而是新增任务并展示 `retry_of_task_id`；移除了后端不支持、且会被下次同步撤销的“清理已完成/从列表移除”；模型安装、Tool 和 Voice 等非 Pipeline 任务不再套用七阶段 Pipeline 时间线；失败任务直接显示后端错误码、阶段和详情，历史任务参数从 `/tasks/{id}/spec` 补读。本地浏览器模式已逐页复核 Workbench、TaskCenter、SubtitleWorkshop、VoiceLab、EnginesResources 和 Settings，未发现控制台错误；这不包含 Tauri 原生文件对话框与正式窗口验收。

`vite.config.ts` 已忽略 `src-tauri/target/**`，避免 Windows 下 Tauri 开发期 Vite 监视 Cargo 的 `.pdb` 文件触发 `EBUSY`。这是一项开发环境兼容配置，不是业务架构变化。

说明：

- 当前 `src` 语法编译通过。
- 完整验证应使用项目 `.venv` 运行 `python -m pytest`，并在 `desktop/` 中运行 `npm run build`。

## 5. 当前项目阶段判断

当前项目不应再定义为 Phase 2 中期。

更准确的定位：

> Phase 2 后段：旧 GUI、旧 pipeline 包、旧字幕脚本包已经从源码树移除，新 core 主干及主要公共契约已建立并被调用；当前剩余工作是兼容入口收束和残留旧依赖压薄。

## 6. 当前最高优先级缺口

1. 在正式 APP 进程复核 Qwen3-TTS 状态展示，确认真实可用状态不会被受限探测误报。
2. 选择是否验收 Qwen3-ASR；若选择，执行 `Qwen3-ASR → DeepSeek → Qwen3-TTS` 真实 Pipeline，并验证两个 Worker 顺序退出。
3. 在批量 GUI 设计前决定是否新增 batch task、聚合状态和取消契约。
4. 将 Voice Design/Clone/Preview 迁移到隔离 Worker；迁移前不作为稳定 GUI 能力。
5. 确定模型与环境保留策略后再清理缓存、权重和重复依赖，随后按事实清单整理 GUI。
6. 兼容层与 Ruff 剩余项按功能域分批清理，不进行无边界自动修复。

## 7. DOCS 维护规则

- 活跃文档不得再把旧计划中的状态当成当前事实。
- 凡是描述项目进度，必须先对照本文和当前源码结构。
- 归档文档不需要逐条改写，但 README 必须明确归档文档不是当前基线。
- 如果源码状态继续变化，先更新本文，再更新 roadmap、contract、domain 文档。
