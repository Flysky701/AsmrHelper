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
3bd5c4a refactor: 桌面 UI 重设计 + LLM 模型管理重构 + 文档架构重组
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

> pipeline 主执行器已经迁到 `core/orchestration/pipeline`，剩余问题是 execution profile 结构、任务状态字段、artifact/preview 语义与主链路契约尚未完全对齐。

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
- 当前仍是进程内轻量任务系统，不是持久化调度系统。
- 当前 `TaskStatus` 还缺少主链路契约中需要的显式 `stage`、`error`、`created_at / started_at / finished_at`、`artifact_set_id`。

### 当前桌面端状态

当前桌面端在：

```text
desktop/
```

当前状态：

- `Workbench` 已能选择文件、配置参数、调用 `/pipeline/run`。
- `TaskCenter` 已能展示任务、取消、重试、展示产物入口和日志详情。
- `EnginesResources` 已接入模型安装状态、异步安装和进度轮询。
- 桌面端已经不是空壳，也不是未接后端阶段。

当前仍缺：

- Workbench 仍主要走兼容 `/pipeline/run`，还不是 `POST /sessions -> POST /tasks` 主路径。
- TaskCenter 仍有基于 message/detail/progress 的阶段推断，尚未完全消费后端显式 `stage`。
- 参数快照仍偏旧平铺字段，没有完全迁到主链路数据参数契约。

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

结果：`122 passed`。

启动环境使用 Python 3.12.13，`scripts/verify_env.py` 已确认 FastAPI、Uvicorn、HTTP API（91 routes）可用。

本地 ASR / 分离 / 混音依赖已移入 `audio` 可选组，避免 Demucs/CUDA PyTorch 阻塞 API 与桌面端首次启动；需要本地完整流水线时使用 `setup.ps1 -Models` 或 `setup.ps1 -Full` 安装。

桌面端已验证：使用 `E:\Dependencies\nodejs` 的 Node v24.18.0、npm v11.16.0 执行 `npm ci` 与 `npm run build` 通过；Rust 1.97.1/Cargo 1.97.1 已安装，`npm run tauri -- build` 通过并生成 `desktop/src-tauri/target/release/asmr-helper.exe`。该程序已启动，后端 `/health` 返回正常。

`vite.config.ts` 已忽略 `src-tauri/target/**`，避免 Windows 下 Tauri 开发期 Vite 监视 Cargo 的 `.pdb` 文件触发 `EBUSY`。这是一项开发环境兼容配置，不是业务架构变化。

说明：

- 当前 `src` 语法编译通过。
- 完整验证应使用项目 `.venv` 运行 `python -m pytest`，并在 `desktop/` 中运行 `npm run build`。

## 5. 当前项目阶段判断

当前项目不应再定义为 Phase 2 中期。

更准确的定位：

> Phase 2 后段：旧 GUI、旧 pipeline 包、旧字幕脚本包已经从源码树移除，新 core 主干已建立并被调用；当前剩余工作是契约落码、兼容入口收束、状态/产物/预览字段对齐，以及残留旧引用修复。

## 6. 当前最高优先级缺口

1. 先按 [字段契约约束 V1](../contracts/field-contracts-v1.md) 补齐 Task、Service、TTS、Artifact 等横向字段规则。
2. 按 [基础设施契约 V1](../contracts/infrastructure-contracts-v1.md) 统一日志事件、模型字段、CapabilityOption、高级参数和 RuntimeBinding 边界。
3. 将 `PipelineService.create_pipeline_task_spec()` 生成的 execution profile 对齐 [主链路 V1 数据参数契约](../contracts/mainline-v1-data-parameters.md)。
4. 更新 `core/orchestration/pipeline/planner.py`，使其优先消费 `profile_version + stages + profiles`，并保留旧结构兼容。
5. 扩展 `TaskStatus`，补齐主链路需要的 `stage / error / timestamps / artifact_set_id`。
6. 将 Workbench 从兼容 `/pipeline/run` 逐步迁到 `session + task` 主路径。
7. 将 TaskCenter 从阶段推断改为消费后端显式状态、artifact 和 preview。

## 7. DOCS 维护规则

- 活跃文档不得再把旧计划中的状态当成当前事实。
- 凡是描述项目进度，必须先对照本文和当前源码结构。
- 归档文档不需要逐条改写，但 README 必须明确归档文档不是当前基线。
- 如果源码状态继续变化，先更新本文，再更新 roadmap、contract、domain 文档。
