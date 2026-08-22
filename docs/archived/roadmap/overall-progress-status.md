# AsmrHelper 总体进度状态

日期：2026-08-19（源码结构基线：2026-05-27；最新验证：2026-08-19）

## 1. 事实源

本状态文档以当前 Git 提交和源码结构为准，不再沿用旧 Phase 2 计划里的过时判断。

当前事实基线见：

- [当前源码基线](current-source-baseline.md)
- [2026-07-23 架构与文档审计（历史快照）](../archived/roadmap/current-architecture-and-doc-audit-2026-07-23.md)

后续如果本文与旧计划、归档文档或历史 roadmap 冲突，以当前源码基线为准。

## 2. 总体判断

当前项目已经越过“架构定义”和“Phase 2 中期迁移”阶段。

更准确的状态是：

> 主线已进入收尾审计：旧 GUI、旧 pipeline/字幕包以及无运行时引用的 `ModelManager/core.translate` 兼容入口均已移除；剩余工作集中在正式窗口人工验收、可选 Provider 实机验收和高复杂度算法函数的分阶段拆分。

2026-07-24 的运行验证补充：项目全量测试为 `166 passed`，HTTP 环境验证发现 88 条路由，前端构建和 Tauri release build 均已通过，生成的桌面程序可连接健康检查正常的本地后端。该结果只覆盖基础启动与构建；本地音频引擎仍取决于 `audio` 可选依赖、模型权重和提供方配置。

2026-07-26 的桌面 P0 修复补充：通用 API client 已支持 `204`/空响应并统一 API 地址与错误解析；Tauri 已补文件对话框 capability 和本地音频 asset protocol；字幕、台本、音频和目录选择已按用途分离；TaskCenter 通过 Artifact 文件接口播放产物，SubtitleWorkshop 与 VoiceLab 已接入统一播放器；未落地的预设 CRUD 和音色修改入口已明确禁用，不再表现为可操作按钮。桌面前端构建、Tauri release build 和 HTTP 契约测试均通过，release 程序已实机启动并确认原生音频文件对话框可用。

2026-07-26 的桌面 P1 修复补充：Workbench 的 ASR、TTS、LLM 和分离选项改为读取 `/capabilities`，不再以客户端常量作为事实源；提交任务前调用 `/runtime/check-task-readiness`，后端按启用阶段校验 provider、model、模型可执行状态和云端凭据，并返回结构化问题与处理入口。能力目录同时删除了运行时未注册的 MDX，分离 provider 统一为真实运行时 `demucs`。默认主链路 readiness 已在当前环境验证通过。

2026-07-28 的交叉检查修复补充：字幕翻译真实运行分支的 `Path` 未定义问题已修复；readiness 已成为 Pipeline 创建与 prepare 阶段的后端权威门禁，并覆盖 Edge TTS、实际 FFmpeg 可执行文件和输入媒体解码；DeepSeek 默认模型已统一到 LLM Registry。随后完成历史测试与执行配置清理：CLI/batch 默认参数统一归一化为 StageProfile V1，planner 拒绝旧 profile，测试中的假 provider 已修正；桌面生产构建通过，Ruff 高风险 `F821/F601` 已清零。

2026-07-30 的手动验收补充：默认单文件完整链路 `demucs/htdemucs → faster-whisper-base → DeepSeek → Edge TTS → FFmpeg` 已使用真实音频执行通过，任务正常完成并生成最终产物。批量任务、异常恢复和其他 Provider 不包含在本次结论中。

2026-07-30 的 P1.5 第一批补充：Workbench 已直接消费 CapabilityOption 的基础类型参数；TTS 声线从引擎接口动态加载，Qwen3 音色档案按可用状态和引擎过滤，`voice_profile_id` 已按契约进入 `provider_options`。桌面生产构建通过。

2026-07-30 的 Provider / Model 接入流程补充：流程已精简为“确认上游、完成 Server、真实验收”三步；运行模型 ID 与资源项 ID 通过 `capability_models` 显式映射，自动守卫保留运行关键一致性检查。

2026-07-30 的第一批参数校准补充：Faster-Whisper 的 VAD、Beam、提示词和无语音阈值已与锁定版本的真实接口统一，Edge TTS 的公共速度倍率会转换为上游 rate 百分比；直接能力调用和 Pipeline readiness 均会提前检查公开参数。参数校准后的默认真实音频主链路已经重新执行通过。

2026-07-31 的 Edge TTS 稳定性补充：失败任务与成功重试使用相同参数，确认问题来自瞬时 WebSocket 连接超时。Edge 批量句子改为最多 4 并发、单句网络失败最多尝试 3 次，并提供可选 HTTP 代理参数；项目级代理合成已生成有效 WAV，重启后的 APP 侧验证也已完成。最新全量测试为 `199 passed`。

2026-07-31 的多引擎恢复补充：ASR/TTS 可选 Provider 已重新接入项目模型目录、Pipeline 时间线和资源安装流程；Workbench 会提交明确模型，依赖冲突不再被误报为安装成功。2026-08-18 收口后的当前注册范围为 ASR `faster_whisper/fun_asr/qwen3_asr`、TTS `edge/qwen3/voxcpm2`、LLM `deepseek/openai` 和分离 `demucs`；真实验收状态单独记录在 [多引擎支持现状](multi-engine-status.md)。

2026-08-03 的后端 P0 验收补充：顺序批量任务已验证单项 TTS 失败不会阻塞后续任务，任务状态、失败阶段和 Artifact 归属保持隔离；Edge 瞬时失败、模型下载中断重试、Worker 异常退出清理、取消后新任务重提均有确定性恢复验收。批处理已接入权威 readiness，失败项保留输入路径，直接执行 `verify_env.py` 的项目根解析已修复。全量测试 `226 passed`，桌面生产构建通过。当前先收束后端事实和安装边界，GUI 整理延后。

2026-08-19 批量产品闭环已落地：新增持久化 BatchRun、稳定 batch_id、子任务列表、聚合进度、整批取消、失败项重提和重启中断事实；桌面增加“批量处理”页，支持目录递归扫描、清单选择、同名字幕发现、输出目录和并行度。每个文件仍是独立 Pipeline Task，Worker 异常明确失败，不承诺自动重启或跨 APP 重启续跑。

同轮验证为：`343 passed`、Ruff 默认规则全量通过、92 条 API 路由环境自检通过、桌面生产构建与 Tauri release build 通过；生成程序位于 `desktop/src-tauri/target/release/asmr-helper.exe`。正式启动器随后连续 2 轮通过“启动—标准关闭—APP/后端退出—端口释放—PID 文件清理”验收。活跃 Markdown 文档无本地断链；Ruff `C901` 仍记录 35 个有运行时引用的复杂度热点，应分阶段拆分而不是按死代码删除。这些结果证明构建、契约与生命周期闭环，不替代正式窗口中的批量目录选择、取消和失败重提人工验收。

2026-08-04 已完成 [后端能力事实清单](backend-capability-baseline.md)，后续以“已实现、环境可执行、真实验收、已接线、受限”五级状态约束 GUI 和清理工作。Voice Design/Clone/Preview、批量任务管理和未验收 Provider 不再因存在路由或页面入口而被视为已完成能力。

## 3. 当前已完成

- `src/gui/` 已移除，不再作为当前产品或文档基线。
- `src/core/pipeline/` 已移除，pipeline 主路径已迁到 `src/core/orchestration/pipeline/`。
- `src/core/script_to_subtitle/`、`src/core/subtitle_generator.py`、`src/core/script_processor.py` 已移除，脚本与字幕能力已迁入 `src/core/subtitles/`。
- `src/core/tasks/` 已建立，`TaskService` 已委托 `TaskRegistry`。
- `src/core/engines/asr`、`llm`、`tts`、`separator` 已存在并被 pipeline executor 消费。
- 桌面端 `desktop/` 已完成第一轮页面重构和后端接线，不是空壳阶段。
- 模型资源与安装链路近期继续推进，已包含异步安装、进度状态、按需安装 Python 依赖等能力。
- P0 已修复字幕服务的旧模块懒加载，并有真实 runtime 导入回归测试。
- P1 已完成后端主链路数据收束：HTTP、CLI 与 batch 最终统一为 StageProfile V1，planner 不再接受旧 profile；TaskStatus/API 已提供显式 stage、时间线、结构化 error 与 artifact_set_id，pipeline executor 显式回写阶段。
- Workbench 已切换到 `POST /pipeline-runs` 和统一 StageProfile；TaskCenter 已消费后端显式阶段、错误与终态历史。
- 终态任务与 Artifact 索引已持久化到 SQLite；重启时删除未完成任务，历史任务保持只读。
- Provider 设置已统一为 Provider v1 包络，凭据只读状态与真实连通性测试已落码。
- TaskResult、Artifact 与 Preview 公共语义已统一，TaskCenter 不再猜测主产物或可播放类型。
- CapabilityOption 已补齐稳定约束；模型资源状态已区分“已安装”和“当前可执行”。
- RuntimeEvent 已按任务生成单调递增序列；SSE、TaskCenter 日志和模型安装增量消息使用同一事件结构。
- 桌面 P0 可用性缺口已收束：文件类型选择、空响应、基础音频预览、关键错误反馈和无效按钮均已处理。
- 桌面 P1 已接入后端能力目录与阶段级 readiness；不可执行配置会在入队前被拦截，并引导至设置或引擎资源页。
- 持久 BatchRun 与桌面批量处理页已接入；批次复用工作台执行配置，并通过独立子任务保留错误和 Artifact 归属。

## 4. 当前仍缺

### 主链路契约尚未完全落码

DOCS 已经收束到：

- [主链路契约 v1](../contracts/mainline-v1.md)
- [数据结构契约 v1](../contracts/schemas-v1.md)
- [Provider 与设置契约 v1](../contracts/provider-v1.md)
- [兼容与迁移说明](../contracts/compatibility.md)

当前主链路请求、任务状态、Provider 设置、结果语义、模型可执行状态和 RuntimeEvent 已经落码。旧 Pipeline 与 Tool 同步入口已删除，HTTP 只支持 V1 新客户端；剩余工作集中在内部模型瘦身。

### P0 已修复残留旧引用

当前已发现：

```text
src/app/services/script_subtitle_service.py
```

原先懒加载已删除的：

```text
src.core.script_to_subtitle
```

已改为 `src.core.subtitles.script_to_subtitle`，实际 runtime 导入已由测试覆盖。

### 兼容层清理已完成

- `ModelManager` 与 `src/core/translate` 已删除，core 根导出同步收口，并由负向架构测试防止复活。
- Translator、缓存、质量检测和术语库只保留 LLM 域正式实现；字幕工具只保留 `core/subtitles` 正式实现。
- `/tools/*`、`/pipeline/run` 和 `/pipeline/tasks` 均已删除；公共 HTTP 不再返回路径型兼容结果。

## 5. 功能域当前状态

| 功能域 | 当前状态 |
|---|---|
| 1 工作空间与输入管理 | 已落地并接入 Workbench 主路径 |
| 2 单任务 pipeline 编排执行器 | 主执行器与桌面正式入口已迁移，Planner 拒绝旧 execution profile |
| 3 统一任务生成与任务队列 | 终态历史已持久化；低并发场景继续使用进程内线程，不建设独立调度器 |
| 4 单步工具执行体系 | 已接入主干，继续收束兼容 DTO |
| 5 模型与运行资源管理 | 已落地；阶段级 readiness 已接入 Workbench，安装链路继续增强 |
| 6 配置与提供方接入管理 | Provider v1 设置、凭据状态、草稿验证和真实连通性测试已落地 |
| 7 字幕与文本资产管理 | 已迁入 `core/subtitles`，残留旧引用已修复 |
| 8 结果资产与产物索引管理 | TaskResult 与 Artifact 公共结构已统一并持久化 |
| 9 结果预览与人工确认 | TaskCenter 已按 Artifact 声明展示主产物与音频预览入口 |
| 10 TTS 引擎管理 | Edge 已验收；Qwen3 已通过主链路；VoxCPM2 已接线、待安装和验收 |
| 11 LLM 能力管理 | DeepSeek 已验收；OpenAI 已接线，待配置凭据和验收 |
| 12 ASR 引擎管理 | Faster-Whisper 已验收；Qwen3-ASR 已通过可选主链路；Fun-ASR 独立推理已通过、Pipeline 待验收 |

## 6. 推荐下一步

### P1.5：参数与能力细化

- 在正式 APP 中用短样本复核批量目录扫描、整批取消和失败项重提交互。
- 按实际需要完成 Fun-ASR 的 Pipeline 级短样本产物验收，并为未安装的 VoxCPM2 保持真实不可用状态。
- 后端基线稳定后，再对照真实 API 整理 GUI 页面、状态和组件，不新增无后端能力支撑的入口。

## 7. 一句话结论

当前不再是“继续替换旧 pipeline 包”的阶段。

当前核心任务是：

> 多引擎代码链路已经恢复；下一步按需安装并逐个完成真实音频验收，不批量扩张。
