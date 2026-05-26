# AsmrHelper 总体进度状态

日期：2026-05-27

## 1. 事实源

本状态文档以当前 Git 提交和源码结构为准，不再沿用旧 Phase 2 计划里的过时判断。

当前事实基线见：

- [当前源码基线](current-source-baseline.md)

后续如果本文与旧计划、归档文档或历史 roadmap 冲突，以当前源码基线为准。

## 2. 总体判断

当前项目已经越过“架构定义”和“Phase 2 中期迁移”阶段。

更准确的状态是：

> Phase 2 后段：旧 GUI、旧 pipeline 包、旧字幕脚本包已经从源码树移除，新 core 主干已建立并被调用；当前剩余工作是契约落码、兼容入口收束、状态/产物/预览字段对齐，以及残留旧引用修复。

## 3. 当前已完成

- `src/gui/` 已移除，不再作为当前产品或文档基线。
- `src/core/pipeline/` 已移除，pipeline 主路径已迁到 `src/core/orchestration/pipeline/`。
- `src/core/script_to_subtitle/`、`src/core/subtitle_generator.py`、`src/core/script_processor.py` 已移除，脚本与字幕能力已迁入 `src/core/subtitles/`。
- `src/core/tasks/` 已建立，`TaskService` 已委托 `TaskRegistry`。
- `src/core/engines/asr`、`llm`、`tts`、`separator` 已存在并被 pipeline executor 消费。
- 桌面端 `desktop/` 已完成第一轮页面重构和后端接线，不是空壳阶段。
- 模型资源与安装链路近期继续推进，已包含异步安装、进度状态、按需安装 Python 依赖等能力。

## 4. 当前仍缺

### 主链路契约尚未完全落码

DOCS 已经收束到：

- [字段契约约束 V1](../contracts/field-contracts-v1.md)
- [主链路 V1 契约](../contracts/mainline-v1-contract.md)
- [主链路 V1 数据参数契约](../contracts/mainline-v1-data-parameters.md)

但代码仍存在差距：

- `PipelineService.create_pipeline_task_spec()` 仍生成旧式 `execution_profile.pipeline + stages`。
- `core/orchestration/pipeline/planner.py` 仍主要消费旧结构。
- Workbench 仍调用兼容 `/pipeline/run`，尚未走 `POST /sessions -> POST /tasks`。

### TaskStatus 还不够支撑 TaskCenter

当前 `TaskStatus` 已有：

- `task_id`
- `state`
- `progress`
- `message`
- `detail`
- `task_type`
- `task_source`
- `session_id`
- `review_state`
- `review_note`

仍缺主链路需要的：

- `stage`
- `error`
- `created_at`
- `started_at`
- `finished_at`
- `artifact_set_id`

因此 TaskCenter 仍在部分场景下通过 `message / detail / progress` 推断阶段。

### 兼容入口仍是桌面主入口

当前 Workbench 已可用，但仍主要通过：

```text
POST /api/v1/pipeline/run
```

这说明桌面端接线已经完成第一轮，但还没有切到主链路契约定义的：

```text
POST /api/v1/sessions
POST /api/v1/tasks
```

### 有实际残留旧引用

当前已发现：

```text
src/app/services/script_subtitle_service.py
```

仍懒加载已删除的：

```text
src.core.script_to_subtitle
```

实际调用会 `ModuleNotFoundError`。这是当前应修复的残留 bug。

### 兼容层还需要瘦身

- `ModelManager` 已是 deprecated 兼容层，但仍存在。
- `src/core/translate` 仍存在，部分 TTS/LLM/兼容路径仍引用其中能力。
- app service 层仍承担一些 DTO 映射和旧字段拼装工作，需要继续压薄。

## 5. 功能域当前状态

| 功能域 | 当前状态 |
|---|---|
| 1 工作空间与输入管理 | 已落地，需接入 Workbench 主路径 |
| 2 单任务 pipeline 编排执行器 | 主执行器已迁到 `core/orchestration/pipeline`，需对齐新 execution profile 和状态字段 |
| 3 统一任务生成与任务队列 | 轻量任务系统已落地，需补 stage/error/timestamps/artifact_set_id |
| 4 单步工具执行体系 | 已接入主干，继续收束兼容 DTO |
| 5 模型与运行资源管理 | 已落地并继续增强安装链路 |
| 6 配置与提供方接入管理 | 已有 capability descriptor / execution profile builder，需与主链路数据契约统一 |
| 7 字幕与文本资产管理 | 已迁入 `core/subtitles`，需修残留旧引用 |
| 8 结果资产与产物索引管理 | 轻量可用，需与 TaskStatus / preview 合流 |
| 9 结果预览与人工确认 | 轻量可用，需成为 TaskCenter 唯一结果消费入口 |
| 10 TTS 引擎管理 | 主干已落地，VoxCPM2 等能力继续扩展 |
| 11 LLM 能力管理 | 主干已落地，模型参数和 provider 默认值仍在调整 |
| 12 ASR 引擎管理 | 主干已落地 |

## 6. 推荐下一步

### P0：修真实残留引用

- 修 `script_subtitle_service.py`，改为加载 `src.core.subtitles.script_to_subtitle`。
- 补或更新对应测试，防止旧路径复活。

### P1：契约落码

- 先按字段契约补齐 Task、Service、Capability、TTS、Artifact 等横向字段。
- 更新 `PipelineService.create_pipeline_task_spec()`。
- 更新 `core/orchestration/pipeline/planner.py`。
- 让新旧 execution profile 在过渡期都可执行，但新结构优先。

### P2：任务状态补齐

- 扩展 `TaskStatus`。
- 更新 tasks API schema。
- 让 pipeline executor 回写显式 `stage`。

### P3：桌面主链路切换

- Workbench 从 `/pipeline/run` 迁到 `session + task`。
- TaskCenter 从阶段推断迁到后端显式 `stage + artifacts + preview`。

### P4：兼容层瘦身

- 收薄 `pipeline_service / audio_tool_service / script_subtitle_service / tts_service / asr_service`。
- 保留兼容路由，但不让兼容字段继续主导新契约。

## 7. 一句话结论

当前不再是“继续替换旧 pipeline 包”的阶段。

当前核心任务是：

> 把已经建立的新 core 主干、桌面端第一轮接线和主链路契约合并到同一条真实可执行路径上。
