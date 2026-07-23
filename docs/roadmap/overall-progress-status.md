# AsmrHelper 总体进度状态

日期：2026-07-23（源码结构基线：2026-05-27；环境与启动验证：2026-07-23）

## 1. 事实源

本状态文档以当前 Git 提交和源码结构为准，不再沿用旧 Phase 2 计划里的过时判断。

当前事实基线见：

- [当前源码基线](current-source-baseline.md)
- [当前架构与文档审计](current-architecture-and-doc-audit-2026-07-23.md)

后续如果本文与旧计划、归档文档或历史 roadmap 冲突，以当前源码基线为准。

## 2. 总体判断

当前项目已经越过“架构定义”和“Phase 2 中期迁移”阶段。

更准确的状态是：

> Phase 2 后段：旧 GUI、旧 pipeline 包、旧字幕脚本包已经从源码树移除，新 core 主干已建立并被调用；当前剩余工作是契约落码、兼容入口收束、状态/产物/预览字段对齐，以及残留旧引用修复。

2026-07-24 的运行验证补充：项目全量测试为 `151 passed`，前端构建和 Tauri release build 均已通过，生成的桌面程序可连接健康检查正常的本地后端。该结果只覆盖基础启动与构建；本地音频引擎仍取决于 `audio` 可选依赖、模型权重和提供方配置。

## 3. 当前已完成

- `src/gui/` 已移除，不再作为当前产品或文档基线。
- `src/core/pipeline/` 已移除，pipeline 主路径已迁到 `src/core/orchestration/pipeline/`。
- `src/core/script_to_subtitle/`、`src/core/subtitle_generator.py`、`src/core/script_processor.py` 已移除，脚本与字幕能力已迁入 `src/core/subtitles/`。
- `src/core/tasks/` 已建立，`TaskService` 已委托 `TaskRegistry`。
- `src/core/engines/asr`、`llm`、`tts`、`separator` 已存在并被 pipeline executor 消费。
- 桌面端 `desktop/` 已完成第一轮页面重构和后端接线，不是空壳阶段。
- 模型资源与安装链路近期继续推进，已包含异步安装、进度状态、按需安装 Python 依赖等能力。
- P0 已修复字幕服务的旧模块懒加载，并有真实 runtime 导入回归测试。
- P1 已完成后端主链路数据收束：PipelineService 生成 `mainline.v1` profile，planner 兼容新旧结构；TaskStatus/API 已提供显式 stage、时间线、结构化 error 与 artifact_set_id，pipeline executor 显式回写阶段。
- Workbench 已切换到 `POST /pipeline-runs` 和统一 StageProfile；TaskCenter 已消费后端显式阶段、错误与终态历史。
- 终态任务与 Artifact 索引已持久化到 SQLite；重启时删除未完成任务，历史任务保持只读。
- Provider 设置已统一为 Provider v1 包络，凭据只读状态与真实连通性测试已落码。
- TaskResult、Artifact 与 Preview 公共语义已统一，TaskCenter 不再猜测主产物或可播放类型。

## 4. 当前仍缺

### 主链路契约尚未完全落码

DOCS 已经收束到：

- [主链路契约 v1](../contracts/mainline-v1.md)
- [数据结构契约 v1](../contracts/schemas-v1.md)
- [Provider 与设置契约 v1](../contracts/provider-v1.md)
- [兼容与迁移说明](../contracts/compatibility.md)

当前主链路请求、任务状态、Provider 设置和结果语义已经落码。`/pipeline/run` 只作为兼容入口保留，不再是桌面主入口；剩余工作集中在 RuntimeEvent、模型资源状态和兼容层瘦身。

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

### 兼容层还需要瘦身

- `ModelManager` 已是 deprecated 兼容层，但仍存在。
- `src/core/translate` 仍存在，部分 TTS/LLM/兼容路径仍引用其中能力。
- app service 层仍承担一些 DTO 映射和旧字段拼装工作，需要继续压薄。

## 5. 功能域当前状态

| 功能域 | 当前状态 |
|---|---|
| 1 工作空间与输入管理 | 已落地，需接入 Workbench 主路径 |
| 2 单任务 pipeline 编排执行器 | 主执行器与桌面正式入口已迁移，旧 execution profile 仅在兼容层保留 |
| 3 统一任务生成与任务队列 | 终态历史已持久化；低并发场景继续使用进程内线程，不建设独立调度器 |
| 4 单步工具执行体系 | 已接入主干，继续收束兼容 DTO |
| 5 模型与运行资源管理 | 已落地并继续增强安装链路 |
| 6 配置与提供方接入管理 | Provider v1 设置、凭据状态、草稿验证和真实连通性测试已落地 |
| 7 字幕与文本资产管理 | 已迁入 `core/subtitles`，残留旧引用已修复 |
| 8 结果资产与产物索引管理 | TaskResult 与 Artifact 公共结构已统一并持久化 |
| 9 结果预览与人工确认 | TaskCenter 已按 Artifact 声明展示主产物与音频预览入口 |
| 10 TTS 引擎管理 | 主干已落地，VoxCPM2 等能力继续扩展 |
| 11 LLM 能力管理 | 主干已落地，模型参数和 provider 默认值仍在调整 |
| 12 ASR 引擎管理 | 主干已落地 |

## 6. 推荐下一步

### P3：基础设施事件与兼容层瘦身

- 完成 RuntimeEvent、CapabilityOption schema 与模型安装事件收束。
- 收薄 `pipeline_service / audio_tool_service / script_subtitle_service / tts_service / asr_service`。
- 保留兼容路由，但不让兼容字段继续主导新契约。

## 7. 一句话结论

当前不再是“继续替换旧 pipeline 包”的阶段。

当前核心任务是：

> 在已经统一的真实主链路上收敛运行事件和模型资源状态，并继续压薄兼容层。
