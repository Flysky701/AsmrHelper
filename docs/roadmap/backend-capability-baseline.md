# AsmrHelper 后端能力事实清单

> 更新时间：2026-08-18
>
> 事实优先级：当前源码与运行探测 > 自动测试 > 真实手动验收 > 设计文档。
> 本文只说明后端现在能做什么、当前机器是否具备条件，以及哪些接口仍只是接线或兼容入口。

## 1. 状态定义

| 状态 | 含义 |
| --- | --- |
| 已实现 | 路由、服务和核心实现存在，自动测试通过 |
| 环境可执行 | 当前机器的依赖、工具、凭据和模型状态检查通过 |
| 真实验收 | 使用真实音频或文本走过正式 API/Pipeline 并得到有效产物 |
| 已接线 | 已进入能力目录或 Registry，但缺环境、模型、凭据或真实验收 |
| 受限 | 能力存在，但同步方式、恢复语义或旧实现使其不能按完整产品能力使用 |

“有 HTTP 路由”不等于“真实验收”；“模型文件存在”也不等于“当前可执行”。

## 2. 当前后端主干

当前合理主链路为：

```text
Tauri / React
→ FastAPI
→ app services
→ Pipeline / Tool orchestration
→ engine registry / isolated runtime worker
→ TaskStatus / RuntimeEvent / Artifact
```

当前应用共注册 `92` 条路由，其中包含 OpenAPI、Swagger、ReDoc 等 4 条文档路由。主链路不是旧 GUI，也不是旧 `src/core/pipeline`。

2026-08-19 BatchRun 交付后的当前自动化基线为 `343 passed`；Ruff、compileall、UV lock、桌面生产构建、Tauri release build 与 Cargo fmt 均通过。批量正式窗口交互仍需单独人工验收。

## 3. 功能域事实

| 功能域 | 当前事实 | 验证程度 | 明确边界 |
| --- | --- | --- | --- |
| Workspace | 可解析项目工作区和输出目录 | 已实现、自动测试 | 不是多项目工作区管理器 |
| Input | 可检查输入路径、媒体类型和伴随字幕 | 已实现、自动测试 | 不保存媒体内容，只保存资产描述 |
| Session | Pipeline/Tool 创建时生成会话并记录输入及输出策略 | 已实现、自动测试 | 当前主要是执行上下文，不是可编辑项目文档 |
| 单文件 Pipeline | StageProfile V1、readiness、后台执行、阶段进度、错误与产物已统一 | 默认 Edge 链路和 Qwen3-TTS 单文件链路真实验收 | 仅进程内线程，不提供跨重启续跑 |
| 批量 Pipeline | 持久化 BatchRun 记录稳定 batch_id、子任务、聚合进度、整批取消和失败项重提；每个输入仍是独立 Pipeline task | BatchRun 生命周期、持久化、取消、重提与 HTTP 契约自动测试通过；桌面生产构建通过 | 重启后未完成批次标记 interrupted，由用户显式重提失败项；不续跑中断任务 |
| Task | pending/running/completed/failed/cancelled/skipped、SSE RuntimeEvent、取消、重提、审核字段 | 已实现、自动测试 | Pipeline retry 创建新 task；重启后的历史任务只读 |
| Queue | 可查看队列快照和 running count | 已实现 | 只是进程内低并发状态，不是持久化调度器 |
| Persistence | SQLite 保存终态 TaskSpec、TaskStatus 和 Artifact | 已实现、重启测试通过 | 启动时删除未完成任务及其 Artifact，不恢复执行 |
| Artifact | 按 task_id 登记主产物、字幕、中间音频和预览类型 | 已实现、批量归属验收通过 | 内部 PipelineResult 仍保留少量路径型字段 |
| Readiness | 校验输入解码、Provider/Model、Python 依赖、系统工具、GPU 和凭据 | 已实现，Pipeline 创建及 prepare 双重检查 | 只检查任务实际选择的阶段；不会自动安装资源 |
| Model catalog | 模型列表、状态、安装、验证、删除和卸载接口存在 | 已实现、自动测试 | “installed”和“executable”是不同状态 |
| Model install | 异步安装任务、串行大模型下载、真实错误、超时和中断重试；默认接口返回统一 TaskStatus | 已实现；中断保留 partial 文件验收通过 | 恢复依赖 Hugging Face 对同一目标目录的续传能力；`sync=true` 仅为诊断兼容入口 |
| Runtime isolation | `main/qwen_tts/qwen_asr/fun_asr` 环境 ID；ASR/TTS 可路由短生命周期 Worker | Qwen3-TTS、Qwen3-ASR 0.6B 直接 API 与双 Worker Pipeline 真实验收 | Worker 异常会失败并清理，不会自动重启 |
| Settings | 设置读取、有效值、校验、脱敏写入和 Provider 连通性测试 | 已实现、自动测试 | 旧 `api` 设置形状仍有兼容解析 |
| Capability | ASR/TTS/LLM/Separator 的模型、默认值和参数 schema 可查询 | 已实现、Workbench 已消费 | 描述符表示支持范围，不表示当前环境已安装 |
| Subtitle | load/parse/normalize/export 等短操作；字幕翻译与台本转字幕后台任务 | 台本纯文本任务已通过真实 HTTP、自动输出和 Artifact 验收；字幕翻译 Tool 已真实验收 | 完整台本对齐仍依赖可执行 ASR 与已配置 LLM |
| Tool task | 分离、格式转换、切分、字幕翻译、音量预览均以“创建即提交”的后台任务执行并登记产物 | 五种工具已连续真实 HTTP 验收；桌面工具页已接线，当前 Tauri 页面与原生文件选择调用已确认 | 音量预览只返回分析结果，不登记文件 Artifact |
| Voice profile | profile 列表、详情、删除、设计、克隆、分析、预览可用；Design/Clone/Preview 进入 `qwen_tts` Worker | Design、Clone、Preview 与 Analyze 均已通过正式 API 真实验收，Task/Artifact 归属正确 | 属于 Qwen3-TTS 专属扩展能力，不承诺其他 TTS Provider 具备等价功能 |

## 4. Provider 与模型事实

### 4.1 当前能力目录

| 类别 | Provider | 默认模型 | 当前机器 | 真实验收 |
| --- | --- | --- | --- | --- |
| Separator | `demucs` | `htdemucs` | 可执行 | 已通过 |
| ASR | `faster_whisper` | `faster-whisper-base` | Tiny/Base/Small/Medium/Large-v3 均被状态服务判定可执行 | Base 已通过；其他尺寸未逐个验收 |
| ASR | `qwen3_asr` | `qwen3-asr-0.6b` | 0.6B/1.7B 权重和 `qwen_asr` 环境存在，CPU Torch 可用 | 0.6B 已通过直接 HTTP API，并进入合成样本双 Worker Pipeline |
| ASR | `fun_asr` | `fun-asr-nano-2512` | Nano 权重与 `fun_asr` 环境可执行 | 独立运行时短音频真实转写已通过；Pipeline 待验收 |
| LLM | `deepseek` | `deepseek-chat` | 凭据已配置 | 已通过 |
| LLM | `openai` | `gpt-4o-mini` | 未配置凭据 | 待验收 |
| TTS | `edge` | `default` | 可执行 | 已通过；瞬时网络失败有重试 |
| TTS | `qwen3` | `qwen3-custom-voice` | 权重和 `qwen_tts` 环境存在 | CustomVoice 已通过用户音频单文件 Pipeline 和合成样本双 Worker Pipeline；Base/VoiceDesign 未验收 |
| TTS | `voxcpm2` | `voxcpm2` | 模型和 Python 包均缺失 | 待验收 |

2026-08-07 已将 `.venv`、`qwen_tts`、`qwen_asr` 和 `fun_asr` 全部迁移到项目内 UV Python 3.12.13。2026-08-18 将 FunASR 固定为锁文件中的 `1.3.26`，补齐 `torchaudio` 并把 Transformers 限制在 5.0 以下；三个隔离环境的依赖一致性检查与模块导入均通过，Qwen3-ASR 0.6B、Qwen3 CustomVoice 和 Fun-ASR Nano 均完成真实推理。旧环境仅移动为 `.runtimes/*-backup-*` 备份，尚未删除。

### 4.2 默认产品组合

当前唯一可以定义为默认已验收组合的是：

```text
demucs/htdemucs
→ faster_whisper/faster-whisper-base
→ deepseek/deepseek-chat
→ edge/default 或 qwen3/qwen3-custom-voice
→ ffmpeg
```

Fun-ASR、Qwen3-ASR、VoxCPM2、OpenAI 和其他 Whisper/Qwen 变体均属于可选能力，不应进入默认安装承诺。

## 5. 本机环境与资产现状

2026-08-07 环境重建后的核对结果：

| 路径 | 大小 | 判断 |
| --- | ---: | --- |
| `.venv` | 约 1.02 GB | FastAPI、Edge TTS、基础音频链路和开发测试；Qwen/FunASR 已移出主环境 |
| `.runtimes/qwen_tts` | 约 4.55 GB | 项目内 Python 3.12.13；Qwen3-TTS CUDA 依赖与真实合成已验收 |
| `.runtimes/qwen_asr` | 约 1.22 GB | 项目内 Python 3.12.13、CPU Torch；0.6B 直接 ASR 已真实验收 |
| `.runtimes/fun_asr` | 约 1.1 GB | 项目内 Python 3.12.13、CPU Torch；依赖一致且 Nano 短音频转写已通过 |
| `models/funasr` | 约 1.9 GB | Fun-ASR Nano 权重存在且可加载；MLT 变体未安装 |
| `models/whisper` | 约 5.08 GB | 五个尺寸同时存在，默认只需要 Base |
| `models/qwen3tts` | 约 12.65 GB | CustomVoice/Base/VoiceDesign 同时存在，只有 CustomVoice 已验收 |
| `models/qwen3asr` | 约 6.13 GB | 0.6B/1.7B 同时存在；0.6B 已直接推理验收，1.7B 未验收 |
| `.uv-cache` | 约 10.18 GB | 可重建依赖缓存，不是业务能力 |
| `desktop/src-tauri/target` | 约 8.04 GB | 可重建 Rust/Tauri 构建产物 |
| `.cache` | 约 0.88 GB | 下载和工具缓存，应按目录确认后清理 |

当前目标环境边界应是：

- `.venv`：FastAPI、Edge TTS、基础音频链路和开发测试；
- `.runtimes/qwen_tts`：Qwen3-TTS；
- `.runtimes/qwen_asr`、`.runtimes/fun_asr`：按用户选择保留，继续分别记录 Pipeline 验收边界；
- VoxCPM2 等未安装能力不进入默认环境。

环境精简必须通过重新解析依赖和重建环境完成，不手工删除单个传递依赖。

## 6. 当前兼容层

### 已完成兼容层删除

- `src/core/model_manager.py`：仓库运行时无引用，已删除；模型服务使用各领域 Registry。
- `src/core/translate`：实现已迁到 `core.engines.llm` 和 `core.subtitles`，弃用转发已删除。
- `src/core/__init__.py` 只保留包说明，不再维护根包懒加载导出；具体能力从所属领域模块导入，旧入口的负向架构测试已删除；维护现有功能行为测试。
- `/tasks/{id}/review-status`、POST `/review-note`、`/task-queue` 已删除；使用 PATCH `/tasks/{id}/review`、PUT `/tasks/{id}/review-note` 和 GET `/tasks/queue`。
- 重复的 Pipeline/Tool/Artifact 任务结果查询和 `/settings/effective` 已删除；结果由 `/tasks/{id}/result` 查询，设置由 `/settings` 查询。
- 工具目录为 GET `/tools`，创建并提交工具任务为 POST `/tool-runs`。台本 HTTP 接口统一使用 `script-to-subtitle`，内部持久化 TaskType 保留 `subtitle.script_to_vtt`。
- Pipeline 与 Tool 的旧手动启动/同步执行 HTTP 入口已删除；创建接口是唯一正式执行入口，结果由 GET 查询。

### 现在不能删除

- `src/core/tts`：Edge/Qwen 实际实现、Voice Profile 和 Voice Designer 仍在其中。
- `src/core/asr`：Faster-Whisper Registry 仍创建其中的 `ASRRecognizer`。
- `src/core/vocal_separator`：Demucs Registry 仍创建其中的 `VocalSeparator`。
- `src/mixer`：Pipeline 和工具服务仍直接使用 `Mixer`。
- `asmr_bilingual.py`、`batch_process.py`：README 仍公开为兼容 CLI。

删除这些旧命名模块前，必须先把真实实现迁入 `core/engines` 或新的领域目录，而不是只删除导入入口。

## 7. GUI 必须遵守的后端边界

- Workbench 可以使用：能力目录、StageProfile V1、readiness、单文件后台任务、取消、活动任务重提和 Artifact 结果。
- Workbench 的多文件提交仍是若干独立任务；正式批次管理由“批量处理”页面和 `/batch-runs` 契约负责。批次支持整批取消与失败项重提，但不宣称跨重启续跑。
- TaskCenter 可以展示终态历史和活动任务；历史任务不能原地重试，只能重新提交。
- TaskCenter 已按 Task V1 修正重试语义：本会话失败任务重试时创建新任务并保留 `retry_of_task_id`，旧任务不再被新 ID 覆盖；页面不再提供后端不存在的“清理/移出任务”操作。非 Pipeline 任务显示自身后端阶段，失败详情直接消费结构化错误，历史参数通过 TaskSpec 补读。
- EnginesResources 可以展示模型与 `installed/executable` 事实；异步安装提交后进入 TaskCenter，统一展示进度、取消、错误和重试，不再由资源页维护另一套任务轮询状态。
- SubtitleWorkshop 已有后端支撑，可在契约范围内整理，不需要重新设计后端。
- VoiceLab 的 profile 浏览、Design、Clone、Preview 可以保留；这些是 Qwen3-TTS 专属扩展，不应显示为所有 TTS 引擎的通用能力。三项生成操作均为创建即提交的后台 Task，结果和试听产物统一从 TaskCenter 获取。
- VoiceLab 的片段分析按后端契约提交 `subtitle_path/audio_language`，并消费 `score/recommended_indices/warnings`；它是克隆表单的同步结构化查询。设计档案的 `custom` 分类和内置预设不可删除边界已对齐。
- AudioTools 已消费后端工具目录和任务创建接口；工具目录读取失败或未声明某项能力时，页面会禁用提交，不把客户端常量当成可用事实。
- SubtitleWorkshop 的字幕翻译已复用 `tool.translate_subtitle`；台本转字幕使用 `subtitle.script_to_vtt` 后台任务，提交后统一到 TaskCenter 查看阶段、错误与产物。完整模式缺少音频、已有字幕模式缺少字幕时会在客户端先拦截。
- “批量处理”页面支持目录递归扫描、文件清单、同名字幕发现、输出目录、批次并行度、总进度、整批取消和失败项重提；配置复用工作台当前预设与引擎参数。
- 旧同步 `pipelineApi.batch` 不再作为产品入口；新桌面端只消费持久化 `/batch-runs`，每个子项的状态和产物继续按 task_id 隔离。

## 8. 后续维护边界

1. 保持 BatchRun 只是 Pipeline Task 的聚合层；不得把批次实现成第二套执行器，也不得把 `interrupted` 宣称为跨重启续跑。
2. 未安装或未配置的可选 Provider 继续展示真实原因；只有用户决定启用后才下载、安装并执行专项验收。
3. `.runtimes/*-backup-*` 不参与当前运行，未经用户确认不删除；多余 Whisper/Qwen 权重也应在确认保留清单后处理。
4. 后续修改 Tauri 对话框、任务状态或播放器时，重新执行正式窗口交互验收；不要用构建成功代替产品验收。

## Task Execution V1 收口进度（2026-08-04）

Pipeline、Tool、模型安装和 Voice Design/Clone/Preview 已接入进程内共享的 `TaskDispatcher` 与 `ExecutorRegistry`。通用 Task HTTP 创建接口会立即提交执行；未知任务类型在创建边界拒绝，已声明但没有 callable 的类型在执行边界明确失败，不会永久停留在 `pending`。重复的 Pipeline start/execute 与 Tool 同步执行 HTTP 入口已删除，避免同一 Task 被二次接管。

`/asr/transcribe`、`/llm/translate`、`/llm/operations/run` 与 `/tts/synthesize` 保留为底层引擎诊断/真实推理验收接口，调用时同步返回领域结果，不提供 Task 取消、重试或历史语义。正式桌面长任务不消费这些接口，而是通过 Pipeline、Tool 或 Voice Task 执行；桌面 API 层已删除未使用的直连封装，只保留 Workbench 需要的 TTS 音色查询。

Task V1 已固定终态不可变、单任务只执行一次、执行器退出后再进入最终取消状态、阶段化错误、基于 `task_id` 的产物归属，以及新重试任务的 `retry_of_task_id`。启动时清理未完成任务的策略不变，重启后恢复的所有终态历史任务统一只读。2026-08-19 新增的 BatchRun 是持久聚合与控制事实，不是 root task 或第二套执行器；仍未引入 executor version、资源标签或分布式队列。

自动化基线为 `254 passed`，覆盖 Tool/字幕/Voice 创建即后台提交、自定义输出目录、台本自动输出、Artifact 归属和失效执行入口守卫。删除 3 条重复同步执行入口后，当前环境自检注册 86 条路由；桌面前端生产构建、Python `compileall` 与 Ruff `F821/F601/F401` 同步通过。

2026-08-07 使用固定非敏感日语测试句完成 `Qwen3-ASR 0.6B → DeepSeek → Qwen3 CustomVoice` 正式 Pipeline。任务 `pipeline-1` 在 `export` 阶段完成，登记混音、双语字幕、TTS WAV 和 ASR 文本四类 Artifact；ASR 文本与测试句一致，字幕包含有效中文翻译，TTS 产物为 24 kHz、6.48 秒 WAV，执行后无 Qwen Worker 残留。该验收不包含用户素材外发。

验收准备同时发现并修复 Edge TTS 的 MP3 输出冲突：以前 `.mp3` 会被 FFmpeg 同时作为输入和输出；现在 MP3 直接保留 Edge 原始结果，WAV 才进入转码，其他扩展名在网络请求前明确拒绝。

Voice 扩展验收使用非敏感合成音频完成：Clone 生成可用档案与 prompt cache，Preview 生成 24 kHz、4 秒 WAV；VoiceDesign 生成 24 kHz、2.56 秒参考音频与 prompt cache；两类任务均登记独立 Artifact，测试档案随后通过正式删除接口清理。Analyze 使用实际音频和字幕返回有效片段、推荐索引与语言不匹配警告。验收中修复其残留旧 ASR 调用：现在统一通过 ASR Runtime 解析资源模型 ID。

Voice 正式路由随后改为后台提交。使用内置 A1 与固定非敏感短句请求 Preview，POST 在 Worker 完成前返回 `201`；`voice.preview-1` 随后在 `preview/completed` 结束并登记一个有效 WAV 主 Artifact，执行后无 Qwen Worker 残留。

环境重建后再次执行默认正式 Pipeline：非敏感合成样本按 `Demucs → Faster-Whisper Base → DeepSeek → Edge TTS → FFmpeg` 完成 `pipeline-1`，终态为 `export/completed`，登记混音、双语字幕、分离人声、TTS 和转写文本 5 个 Artifact。分离人声与 TTS 均为 6.48 秒，字幕包含有效日文原文与中文译文；启动助手同时通过独立端口健康检查、真实 PID、持久日志和退出后端口释放验收。

## 9. 启动与日志事实（2026-08-07）

- `GUIRun.bat` 默认优先启动已有 release；没有 release 时才进入开发模式。`--installed` 不要求 Node/Rust，`--dev` 和 `--release` 才检查构建工具。
- 后端由隐藏进程启动，日志持久写入 `logs/backend.log`；启动失败会显示日志尾部，不再只表现为窗口闪退。
- 后端通过 PID 文件发布实际 Uvicorn 进程号。已实测启动器返回 PID、日志 PID 和活动进程一致，结束后进程被清理。
- 正式 `tauri build` 已生成 `desktop/src-tauri/target/release/asmr-helper.exe`；随后通过 `GUIRun.bat --release` 启动，桌面进程保持响应，并实际请求 capabilities、tasks、presets、voice profiles 和 Edge voices。
- Computer Use 的 `@oai/sky` 组件受宿主目录 `EPERM` 阻断；这项工具故障没有被算作 APP 通过证据，当前窗口交互改由真实 Tauri WebView2 调试连接验收。
- 已通过本地浏览器模式复核 Workbench、TaskCenter、SubtitleWorkshop、VoiceLab、EnginesResources 和 Settings 的真实渲染与后端交互；模型状态、失败阶段/错误、Voice 预设边界和凭据不回显均符合当前事实。
- 2026-08-07 基于最新源码重新完成 Tauri release 构建并用 `GUIRun.bat --installed` 启动；`asmr-helper` 窗口标题正确、进程响应正常，后端健康检查及启动后的 capabilities、tasks、presets、voice profiles、Edge voices 请求均成功且日志无错误。Computer Use 初始化被宿主目录 `EPERM` 阻断后，改用一次性本地 WebView2 CDP 连接真实 Tauri 窗口：工作台、任务中心、音频工具、字幕工坊、音色实验室、引擎与资源和设置 7 个页面均完成实际点击与内容读取；引擎页完成 readiness 后显示 17 个模型及真实凭据状态。点击“添加音频”后页面失焦且主窗口进入模态等待，确认原生文件选择框接管；历史 release 已实机确认“音频”过滤器，相关插件、权限和调用链未改变。
- 同一正式窗口在 TaskCenter 选择仍存在主产物的 `pipeline-2`，成功加载主音频 Artifact；播放器识别时长 8 秒，点击播放后进度由 `0:00` 前进到 `0:02` 且控制按钮切换为暂停，确认任务结果查询、Artifact 文件服务和桌面播放器链路可用。
- 正式窗口关闭曾间歇出现“窗口消失但 APP 与后端仍存活”。当前 Tauri 侧对主窗口 `CloseRequested` 采用 fail-closed 拦截，前端完成未保存状态确认后调用 `WebviewWindow.destroy()`；`GUIRun.bat` 只结束本轮创建的后端 PID，并仅在 PID 文件仍匹配时移除该文件。2026-08-19 最新 release 连续 2 轮完成启动、标准关闭、APP/后端进程结束、8000 端口释放及 PID 文件清理，启动脚本闭环已重新验收。

## 10. Tool 任务与桌面入口验收（2026-08-07）

- 当时的 `POST /api/v1/tool-runs/tasks` 已收口为创建即提交，桌面端只需一次请求即可获得后台 Task。2026-09-10 路径统一为 `POST /api/v1/tool-runs`，后台执行语义不变。
- 使用非敏感合成音频/字幕连续提交分离、格式转换、字幕切分、字幕翻译和音量预览五项任务，全部到达 `completed`；前四项 Artifact 分别归属各自 task_id，音量预览按设计只返回分析结果。
- 分离工具此前忽略自定义输出目录，现已按 `custom-dir` session policy 生成到指定目录并真实复测通过。
- 桌面新增 AudioTools 页面，工具目录是可用性事实源；每次操作创建独立 Task，提交后转到 TaskCenter 查看阶段、错误和产物。生产构建与当前 Tauri 页面点击均已通过，原生文件选择调用已确认进入系统模态对话框。
