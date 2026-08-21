# AsmrHelper 当前源码基线

日期：2026-08-21

## 1. 本文定位

本文是当前源码和文档整理的第一事实源，按当前分支 `codex/full-module-repair` 的工作树编写。它描述源码中已经存在的入口、已删除的旧入口、产品边界和本轮可确认的验证状态；不把设计稿、历史计划或单纯存在的路由当成已验收能力。

事实优先级如下：

1. 当前工作树中的 `src/`、`desktop/`、配置和脚本。
2. 可重复的自动化检查。
3. 标注日期的真实运行验收。
4. 契约和设计文档。
5. `docs/archived/` 中的历史材料只用于追溯。

## 2. 当前版本边界

- 当前分支：`codex/full-module-repair`。
- 本轮整理前的 Git 基线提交：`0484cac`（`优化：补齐功能页面响应式布局`）。工作区原本包含一组尚未提交的死代码删除和兼容层删除；本页把这些当前工作树事实一并纳入核对范围。
- 正式产品入口是 `GUIRun.bat` 启动的 Tauri 桌面端；后端是本机 FastAPI HTTP API；CLI 和 `scripts/` 下脚本是兼容或排障入口，不是 GUI 能力事实源。
- 项目要求 Python `>=3.11,<3.13`。`setup.ps1` 使用项目内 UV Python，并把项目虚拟环境放在 `.venv`；`.runtimes/` 保存 UV Python 和按 Provider 划分的隔离运行时。

## 3. 当前源码结构

### 后端主路径

```text
src/api/http/                     FastAPI 路由、schema 和启动入口
src/app/services/                 应用服务、任务提交和 DTO 映射
src/core/engines/                 ASR、LLM、TTS、separator registry/runtime
src/core/orchestration/pipeline/  Pipeline planner、executor、result mapper
src/core/tasks/                   TaskSpec、TaskStatus、Dispatcher、ExecutorRegistry
src/core/artifacts/               ArtifactRecord、索引和 TaskResult/Preview 视图
src/core/resources/               模型目录、安装、状态和 readiness
src/core/runtime/                 隔离运行时、Router 和短生命周期 Worker
src/core/subtitles/               字幕、台本、清洗、解析、导出和文本工具
```

### 桌面端主路径

```text
desktop/src/pages/                Workbench、TaskCenter、AudioTools、字幕工坊、VoiceLab、资源和设置
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
```

`src/core/__init__.py` 现在只保留包说明，不再维护一套根包懒加载公共 API。具体能力应从所属模块导入，例如 `src.core.engines.llm`、`src.core.subtitles`、`src.core.tasks` 或 `src.core.resources`。

## 5. 当前正式执行入口

| 能力 | 正式入口 | 语义 |
| --- | --- | --- |
| Pipeline | `POST /api/v1/pipeline-runs` | 返回 `202`，创建并提交后台任务 |
| Tool | `POST /api/v1/tool-runs/tasks` | 返回 `201`，创建并提交后台任务 |
| 模型安装 | `POST /api/v1/models/{model_id}/install` | 默认返回 `201` 的 TaskStatus |
| 字幕台本转 VTT | `POST /api/v1/subtitles/script-to-vtt/tasks` | 后台 Task，产物归属 Task |
| Voice Design/Clone/Preview | 对应 `/api/v1/voice/*` | 返回 `201` 的后台 Task |
| 任务查询 | `GET /api/v1/tasks/{task_id}` | TaskStatus 是状态事实源 |
| 结果查询 | `GET /api/v1/tasks/{task_id}/result` 或 `/preview` | 使用 `primary_artifact_id + artifacts` |

`/api/v1/asr/transcribe`、`/llm/translate`、`/llm/operations/run` 和 `/tts/synthesize` 是同步诊断/Provider 验收面，不是桌面长任务入口。桌面端长任务必须通过 Pipeline、Tool 或 Voice Task 提交。

任务审阅的规范入口是 `PATCH /api/v1/tasks/{task_id}/review`；`POST /review-status`、`PUT/POST /review-note` 仍作为现存兼容别名，不能描述为已删除路由。

## 6. 当前任务和结果语义

- `TaskDispatcher` 与 `ExecutorRegistry` 在进程内管理提交、执行、取消和终态；未知任务类型在创建边界拒绝，缺少 callable 的已声明类型在执行边界明确失败。
- `pending`、`running`、`completed`、`failed`、`cancelled`、`skipped` 是任务状态；终态生命周期字段不可再被覆盖，审阅字段可独立更新。
- 取消是协作请求，执行器退出后才写入最终 `cancelled`；重试创建新 Task，并用 `retry_of_task_id` 关联原任务。
- Artifact 按 `task_id` 登记，公共结果使用 `primary_artifact_id`、`artifacts` 和 `warnings`，不再把 `files/primary_output` 作为公共响应契约。
- SQLite 保存终态历史和 Artifact 索引；重启时清理未完成任务，不恢复中断执行；恢复的历史任务只读。
- 当前不引入持久化执行队列、BatchRun 聚合实体或分布式调度。Workbench 多文件是多个独立 Task；`POST /api/v1/pipeline/batch` 仍是同步聚合接口，桌面页面不消费它。

## 7. Provider 和运行时事实

当前 Registry/能力目录包含：

- ASR：`faster_whisper`、`fun_asr`、`qwen3_asr`。
- TTS：`edge`、`qwen3`、`kokoro`、`voxcpm2`。
- LLM：`deepseek`、`openai`。
- Separator：`demucs`。

默认组合为 `demucs/htdemucs → faster-whisper/faster-whisper-base → deepseek/deepseek-chat → edge → ffmpeg`。最新的真实验收证据（[2026-08-07 验收矩阵](../archived/roadmap/final-acceptance-2026-08-07.md)）还覆盖 `qwen3_asr/qwen3-asr-0.6b → deepseek → qwen3/qwen3-custom-voice`；这不代表所有可列出的 Provider 都已在当前机器完成验收。

Qwen3-TTS、Qwen3-ASR 和 Fun-ASR 使用按需隔离运行时；Qwen3-TTS 通过短生命周期 Worker 执行。模型已安装、当前解释器可导入、readiness 通过和真实主链路验收是四个不同状态，界面必须分别展示。

## 8. 本轮验证状态

- 已完成源码引用审计：当前页面没有引用已删除的桌面组件，仓库内没有活跃代码导入 `src.core.model_manager` 或 `src.core.translate`。
- 已确认 `git diff --check` 无空白错误。
- 使用工作区 Python 3.12.13 复用现有 `.venv\Lib\site-packages` 运行全量自动化，结果为 `272 passed`。
- `compileall -q src tests` 与 Ruff `F821/F601/F401` 检查通过。
- 使用桌面端现有 TypeScript/Vite 二进制完成 `tsc -b` 和生产构建，构建通过。
- 项目 `.venv\Scripts\python.exe` 的启动器仍指向已经不存在的 Python；本轮解释器绕行只用于验证，不代表项目环境已修复。
- 本轮没有重新执行真实 Provider 推理或正式桌面窗口验收；截至 2026-08-07 的证据保存在 [历史路线图](../archived/roadmap/) 和 [多引擎支持现状](multi-engine-status.md) 中。

## 9. 后续维护规则

1. 修改入口、字段、状态或 Provider 后，先更新本文，再更新对应契约和 GUI 文档。
2. 活跃文档只能描述当前源码、可重复检查或明确标注日期的验收；旧计划不能充当当前缺口清单。
3. 设计稿必须标注“草案”，不得把草案 API 或字段写成当前实现。
4. 已删除入口只在兼容说明或历史归档中出现，并明确写成已删除。
5. 大量历史记录应进入 `docs/archived/`，当前索引只保留能指导下一次修改的文档。
