# AsmrHelper 当前源码基线

更新：2026-09-29

### 2026-09-29 开发基线整理

- 当前开发基线为 `dev`，承接原实验分支 `33e3ab1` 的全部提交，并整合远程 `master` 的接口统一和无调用代码清理。`master` 保留稳定主线角色，开发基线尚待产品验收。
- 工具目录统一为 `GET /api/v1/tools`，工具任务为 `POST /api/v1/tool-runs`；台本任务为 `POST /api/v1/subtitles/script-to-subtitle/tasks`。
- 设置统一读取 `/settings`，配置导入统一使用 `src.config`。任务结果统一从 `/tasks/{id}/result` 查询；审阅采用 PATCH `/tasks/{id}/review` 与 PUT `/tasks/{id}/review-note`。
- 保留当前工作台、声音库、音色生成规则、任务恢复以及克隆 manifest；旧独立批处理页面继续移除。历史设计及验收材料保留在 `docs/archived/`。
- 当前待处理范围以 [模块边界清单](module-boundary-checklist.md) 为准，其中跳过或待讨论的项目不因本次合并而扩大实施。
- 本次检查结果、历史分支与标签处理见 [基线整理记录](git-baseline-cleanup-2026-09-29.md)。下面保留此前阶段记录，其日期不代表本次重新完成真实模型验收。

### 2026-09-23 体验优化补充

- 导航、工作台与任务中心移除装饰性英文标题及重复说明。
- 设置仅显示选中服务商字段，LLM 模型由远端探测取得，保留折叠的手填入口；LLM/TTS 连接可命名保存并在工作台选择。
- 新增 `openai_compatible` TTS，界面仅展示命名配置、地址和凭据；底层保留模型、音色和指令参数，当前不展示猜测的选项。适配器支持 `/audio/speech` 及聊天音频响应，复用现有时间线适配器。
- 流水线加入默认关闭的 Qwen 对齐阶段；任务中心支持显式阶段恢复，已完成阶段经检查后复用，中断阶段重跑，不包含阶段内恢复。
- 配置方式及接口边界见 [外部 TTS](../providers/openai-compatible-tts.md)。本次外部接口验证使用模拟响应，不代表用户账户上的真实合成验收。
- 版本整理后的拟提交代码快照回归 `530 passed`；TypeScript 与 Vite 生产构建通过。未重建 Tauri release，未进行真实模型推理或付费接口验收。恢复失效规则尚有正确性缺口，见 [本轮版本与验收记录](version-management-2026-09-23.md)。

## 1. 本文定位

本文是当前源码和文档整理的第一事实源，按开发分支 `dev` 的工作树维护。它描述源码中已经存在的入口、已删除的旧入口、产品边界和可确认的验证状态；不把设计稿、历史计划或单纯存在的路由当成已验收能力。

事实优先级如下：

1. 当前工作树中的 `src/`、`desktop/`、配置和脚本。
2. 可重复的自动化检查。
3. 标注日期的真实运行验收。
4. 契约和设计文档。
5. `docs/archived/` 中的历史材料只用于追溯。

## 2. 当前版本边界

- 当前开发分支：`dev`；稳定主线：`master`。
- 本页按当前工作树编写；工作区可能包含尚未提交的用户修改，实施和验证时必须保留并避开无关改动。
- 正式产品入口是 `GUIRun.bat` 启动的 Tauri 桌面端；后端是本机 FastAPI HTTP API；CLI 和 `scripts/` 下脚本是兼容或排障入口，不是 GUI 能力事实源。
- 项目要求 Python `>=3.11,<3.13`。`setup.ps1` 使用项目内 UV Python，并把项目虚拟环境放在 `.venv`；`.runtimes/` 保存 UV Python 和按 Provider 划分的隔离运行时。

## 3. 当前源码结构

### 后端主路径

```text
src/api/http/                     FastAPI 路由、schema 和启动入口
src/app/services/                 应用服务、任务提交和 DTO 映射
src/core/engines/                 ASR、LLM、TTS、separator registry/runtime
src/core/speech/                  当前语音 Provider、规则编译、素材与实验记录
src/core/orchestration/pipeline/  Pipeline planner、executor、result mapper
src/core/tasks/                   TaskSpec、TaskStatus、Dispatcher、ExecutorRegistry
src/core/batches/                 BatchRun 聚合模型
src/core/artifacts/               ArtifactRecord、索引和 TaskResult/Preview 视图
src/core/resources/               模型目录、安装、状态和 readiness
src/core/runtime/                 隔离运行时、Router 和短生命周期 Worker
src/core/subtitles/               字幕、台本、清洗、解析、导出和文本工具
```

### 桌面端主路径

```text
desktop/src/pages/                Workbench、TaskCenter、AudioTools、字幕工坊、VoiceLab、资源和设置
desktop/src/components/           页面布局、任务中心批次面板和复用展示组件
desktop/src/api/                  页面实际使用的按领域 HTTP 封装
desktop/src/hooks/                任务和音频状态轮询
desktop/src/stores/               页面导航、任务、日志、工作台和播放器状态
```

旧的 `desktop/src/components/ui`、`components/shared`、`components/sidebar/LogEntry` 和 `hooks/usePolling` 未被当前页面引用，已从当前工作树移除。页面现在使用各自实际需要的结构和样式，不应恢复这些无调用兼容组件。

## 4. 已删除的旧入口

以下入口已经不属于当前源码，不得再写成“待迁移”或“兼容期仍存在”：

```text
src/core/model_manager.py
src/core/translate/
src/core/pipeline/
src/gui/
src/core/script_to_subtitle/
src/core/subtitle_generator.py
src/core/script_processor.py
desktop/src/pages/BatchProcessing.tsx
```

桌面 PageId `batch-processing` 及其导航、页面映射也已删除；BatchRun 后端契约继续保留。

`src/core/__init__.py` 现在只保留包说明，不再维护一套根包懒加载公共 API。具体能力应从所属模块导入，例如 `src.core.engines.llm`、`src.core.subtitles`、`src.core.tasks` 或 `src.core.resources`。

## 5. 当前正式执行入口

| 能力 | 正式入口 | 语义 |
| --- | --- | --- |
| Pipeline | `POST /api/v1/pipeline-runs` | 返回 `202`，创建并提交后台任务 |
| BatchRun | `POST /api/v1/batch-runs` | 持久聚合多个普通 Pipeline Task，支持整批取消和失败项重提 |
| Tool | `POST /api/v1/tool-runs` | 返回 `201`，创建并提交后台任务 |
| 模型安装 | `POST /api/v1/models/{model_id}/install` | 默认返回 `201` 的 TaskStatus |
| 台本转字幕 | `POST /api/v1/subtitles/script-to-subtitle/tasks` | 后台 Task，产物归属 Task |
| 语音试音生成 | `POST /api/v1/speech/experiments/{id}/generate` | 返回 `202` 的 `speech.generate` 后台 Task |
| 声音库辅助选段 | `POST /api/v1/speech/references/analyze-tasks` | 返回 `202` 的 `speech.reference_analyze` 后台 Task |
| 任务查询 | `GET /api/v1/tasks/{task_id}` | TaskStatus 是状态事实源 |
| 结果查询 | `GET /api/v1/tasks/{task_id}/result` 或 `/preview` | 使用 `primary_artifact_id + artifacts` |

Workbench 统一整理文件选择和目录递归扫描得到的输入清单，并复用同一份 ExecutionProfile 构建逻辑。恰好一个选中输入时提交 `/pipeline-runs`；多于一个输入时先明确提示“本次将创建批次”，再提交 `/batch-runs`。独立的桌面“批量处理”页面和导航入口已删除，后端 BatchRun API、持久记录及兼容 CLI 不受影响。

`/api/v1/asr/transcribe`、`/llm/translate`、`/llm/operations/run` 是同步诊断/Provider 验收面，不是桌面长任务入口。语音当前使用 `/api/v1/speech/*`；旧 `/api/v1/voice/*`、`/api/v1/tts/*` 未挂载，不能作为诊断入口。桌面端长任务通过 Pipeline、Tool 或 Speech Task 提交。

任务审阅的规范入口是 `PATCH /api/v1/tasks/{task_id}/review`，备注使用 `PUT /api/v1/tasks/{task_id}/review-note`；旧 `POST /review-status` 和 `POST /review-note` 已移除。

## 6. 当前任务和结果语义

- `TaskDispatcher` 与 `ExecutorRegistry` 在进程内管理提交、执行、取消和终态；未知任务类型在创建边界拒绝，缺少 callable 的已声明类型在执行边界明确失败。
- `pending`、`running`、`completed`、`failed`、`cancelled`、`skipped` 是任务状态；终态生命周期字段不可再被覆盖，审阅字段可独立更新。
- 取消是协作请求，执行器退出后才写入最终 `cancelled`；重试创建新 Task，并用 `retry_of_task_id` 关联原任务。
- Artifact 按 `task_id` 登记，公共结果使用 `primary_artifact_id`、`artifacts` 和 `warnings`，不再把 `files/primary_output` 作为公共响应契约。
- SQLite 保存任务、Artifact 索引及 Pipeline 恢复清单和阶段检查点。重启时，有恢复清单的未完成任务保留为 `failed / TASK_INTERRUPTED`，其余未完成任务清理。历史任务不能普通重试；符合条件的失败、取消或中断 Pipeline 可显式调用 `/tasks/{id}/resume` 创建新任务，校验后复用已完成阶段，中断阶段重跑。不会自动续跑，也不支持阶段内部恢复。
- BatchRun 持久记录批次输入、子任务和聚合状态，但不成为第二套执行器；每个文件仍创建普通 Pipeline Task。批次历史、总进度、整批取消和失败项重提统一由 TaskCenter 的批次视图管理；进入该视图时加载历史，之后只轮询当前选中的活动批次，不在常驻页面持续拉取全部历史明细。APP 重启后中断批次标记为 `interrupted`，批次控制提供显式失败项重提，不自动续跑；单个子任务另按 Pipeline 阶段恢复规则判断。
- 当前不引入持久化执行队列或分布式调度；旧同步 `POST /api/v1/pipeline/batch` 不作为桌面产品入口。

## 7. Provider 和运行时事实

当前 Registry/能力目录包含：

- ASR：`faster_whisper`、`fun_asr`、`qwen3_asr`。
- Speech 语音能力目录：`edge`、`qwen3`、`voxcpm2`、`openai_compatible`、`fish_audio`、`mimo_audio`；模式和参数按各引擎声明提供，不代表均支持克隆或声音设计。
- LLM：`deepseek`、`openai`。
- Separator：`demucs`。

默认组合为 `demucs/htdemucs → faster-whisper/faster-whisper-base → deepseek/deepseek-chat → edge → ffmpeg`。最新的真实验收证据（[2026-08-07 验收矩阵](../archived/roadmap/final-acceptance-2026-08-07.md)）还覆盖 `qwen3_asr/qwen3-asr-0.6b → deepseek → qwen3/qwen3-custom-voice`；这不代表所有可列出的 Provider 都已在当前机器完成验收。

Qwen3-TTS、Qwen3-ASR 和 Fun-ASR 使用按需隔离运行时；ASR/TTS 可通过短生命周期 Worker 执行。Fun-ASR Nano 已完成独立运行时短音频转写，Pipeline 级验收仍待完成。模型已安装、当前解释器可导入、readiness 通过和真实主链路验收是四个不同状态，界面必须分别展示。

## 8. 历史验证记录（2026-08-22）

- 已完成源码引用审计：当前页面没有引用已删除的桌面组件，仓库内没有活跃代码导入 `src.core.model_manager` 或 `src.core.translate`。
- 已确认 `git diff --check` 无空白错误。
- 使用工作区 Python 3.12.13 复用现有 `.venv\Lib\site-packages` 运行合并后全量自动化，结果为 `345 passed`。
- `compileall -q src tests` 与 Ruff `F821/F601/F401` 检查通过。
- 合并后的 `tsc -b` 通过；Vite 生产构建命令因权限审批超时未实际启动，不写成新的通过结论。
- 远端子分支的同一前端基线已在 2026-08-19 完成生产构建和 Tauri release build；该日期证据保留在能力基线中。
- 项目 `.venv\Scripts\python.exe` 的启动器仍指向已经不存在的 Python；本轮解释器绕行只用于验证，不代表项目环境已修复。
- 本轮没有重新执行真实 Provider 推理或正式桌面窗口验收；截至 2026-08-07 的证据保存在 [历史路线图](../archived/roadmap/) 和 [多引擎支持现状](multi-engine-status.md) 中。

## 9. 后续维护规则

1. 修改入口、字段、状态或 Provider 后，先更新本文，再更新对应契约和 GUI 文档。
2. 活跃文档只能描述当前源码、可重复检查或明确标注日期的验收；旧计划不能充当当前缺口清单。
3. 设计稿必须标注“草案”，不得把草案 API 或字段写成当前实现。
4. 已删除入口只在兼容说明或历史归档中出现，并明确写成已删除。
5. 大量历史记录应进入 `docs/archived/`，当前索引只保留能指导下一次修改的文档。
