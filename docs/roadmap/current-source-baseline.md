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

2026-07-23 已验证：

```text
.venv\Scripts\python.exe -m compileall -q src
```

结果：通过。

```text
.venv\Scripts\python.exe -m pytest -q
```

结果：`166 passed`。

启动环境使用 Python 3.12.13，`scripts/verify_env.py` 已确认 FastAPI、Uvicorn、HTTP API（88 routes）可用。

本地 ASR / 分离 / 混音依赖已移入 `audio` 可选组，避免其阻塞 API 与桌面端首次启动；当前环境已通过 `audio` 安装档安装 CPU PyTorch、Demucs、Faster-Whisper 和 imageio-ffmpeg，并下载 Faster-Whisper Base 权重。最小真实链路（本地音频 → ASR → export）已完成，任务状态为 `completed`。CUDA 仅作为后续性能加速选项，不再是首次本地执行的前置条件。

桌面端已验证：使用 `E:\Dependencies\nodejs` 的 Node v24.18.0、npm v11.16.0 执行 `npm ci` 与 `npm run build` 通过；Rust 1.97.1/Cargo 1.97.1 已安装，`npm run tauri -- build` 通过并生成 `desktop/src-tauri/target/release/asmr-helper.exe`。该程序已启动，后端 `/health` 返回正常。

2026-07-26 完成桌面 P0 可用性修复：API client 支持空响应并统一错误解析；Tauri 原生文件对话框权限已显式配置；文件选择器按音频、字幕、台本和目录分类；TaskCenter、SubtitleWorkshop 与 VoiceLab 的音频入口接入统一播放器；当前后端未支持的预设 CRUD 和音色修改按钮已明确禁用。验证结果为 `npm run build` 通过、Tauri release build 通过、`tests/test_http_api.py` 为 `38 passed`，release 程序已实机确认能够打开带“音频”过滤器的原生文件对话框。

`vite.config.ts` 已忽略 `src-tauri/target/**`，避免 Windows 下 Tauri 开发期 Vite 监视 Cargo 的 `.pdb` 文件触发 `EBUSY`。这是一项开发环境兼容配置，不是业务架构变化。

说明：

- 当前 `src` 语法编译通过。
- 完整验证应使用项目 `.venv` 运行 `python -m pytest`，并在 `desktop/` 中运行 `npm run build`。

## 5. 当前项目阶段判断

当前项目不应再定义为 Phase 2 中期。

更准确的定位：

> Phase 2 后段：旧 GUI、旧 pipeline 包、旧字幕脚本包已经从源码树移除，新 core 主干及主要公共契约已建立并被调用；当前剩余工作是兼容入口收束和残留旧依赖压薄。

## 6. 当前最高优先级缺口

1. 将内部 PipelineResult/ArtifactSet 中的路径型 `primary_output/files` 继续迁到 ArtifactRecord；公共 HTTP 已不再暴露。
2. `core.translate` 当前只保留弃用转发；兼容期结束前不再向其中增加实现。
3. 保持 RuntimeEvent 为进程内诊断时间线；只有出现明确的跨重启审计需求时再评估持久化。

## 7. DOCS 维护规则

- 活跃文档不得再把旧计划中的状态当成当前事实。
- 凡是描述项目进度，必须先对照本文和当前源码结构。
- 归档文档不需要逐条改写，但 README 必须明确归档文档不是当前基线。
- 如果源码状态继续变化，先更新本文，再更新 roadmap、contract、domain 文档。
