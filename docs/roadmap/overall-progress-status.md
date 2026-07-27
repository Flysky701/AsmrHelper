# AsmrHelper 总体进度状态

日期：2026-07-28（源码结构基线：2026-05-27；最新验证：2026-07-28）

## 1. 事实源

本状态文档以当前 Git 提交和源码结构为准，不再沿用旧 Phase 2 计划里的过时判断。

当前事实基线见：

- [当前源码基线](current-source-baseline.md)
- [当前架构与文档审计](current-architecture-and-doc-audit-2026-07-23.md)

后续如果本文与旧计划、归档文档或历史 roadmap 冲突，以当前源码基线为准。

## 2. 总体判断

当前项目已经越过“架构定义”和“Phase 2 中期迁移”阶段。

更准确的状态是：

> Phase 2 后段：旧 GUI、旧 pipeline 包、旧字幕脚本包已经从源码树移除，新 core 主干及主要公共契约已建立并被调用；当前剩余工作集中在兼容入口和旧服务依赖瘦身。

2026-07-24 的运行验证补充：项目全量测试为 `166 passed`，HTTP 环境验证发现 88 条路由，前端构建和 Tauri release build 均已通过，生成的桌面程序可连接健康检查正常的本地后端。该结果只覆盖基础启动与构建；本地音频引擎仍取决于 `audio` 可选依赖、模型权重和提供方配置。

2026-07-26 的桌面 P0 修复补充：通用 API client 已支持 `204`/空响应并统一 API 地址与错误解析；Tauri 已补文件对话框 capability 和本地音频 asset protocol；字幕、台本、音频和目录选择已按用途分离；TaskCenter 通过 Artifact 文件接口播放产物，SubtitleWorkshop 与 VoiceLab 已接入统一播放器；未落地的预设 CRUD 和音色修改入口已明确禁用，不再表现为可操作按钮。桌面前端构建、Tauri release build 和 HTTP 契约测试均通过，release 程序已实机启动并确认原生音频文件对话框可用。

2026-07-26 的桌面 P1 修复补充：Workbench 的 ASR、TTS、LLM 和分离选项改为读取 `/capabilities`，不再以客户端常量作为事实源；提交任务前调用 `/runtime/check-task-readiness`，后端按启用阶段校验 provider、model、模型可执行状态和云端凭据，并返回结构化问题与处理入口。能力目录同时删除了运行时未注册的 MDX，分离 provider 统一为真实运行时 `demucs`。默认主链路 readiness 已在当前环境验证通过。

2026-07-28 的交叉检查修复补充：字幕翻译真实运行分支的 `Path` 未定义问题已修复；readiness 已成为 Pipeline 创建与 prepare 阶段的后端权威门禁，并覆盖 Edge TTS、实际 FFmpeg 可执行文件和输入媒体解码；DeepSeek 默认模型已统一到 LLM Registry。最新全量测试为 `180 passed`，桌面生产构建通过，Ruff 高风险 `F821/F601` 已清零。

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
- CapabilityOption 已补齐稳定约束；模型资源状态已区分“已安装”和“当前可执行”。
- RuntimeEvent 已按任务生成单调递增序列；SSE、TaskCenter 日志和模型安装增量消息使用同一事件结构。
- 桌面 P0 可用性缺口已收束：文件类型选择、空响应、基础音频预览、关键错误反馈和无效按钮均已处理。
- 桌面 P1 已接入后端能力目录与阶段级 readiness；不可执行配置会在入队前被拦截，并引导至设置或引擎资源页。

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

### 兼容层还需要瘦身

- `ModelManager` 已是 deprecated 兼容层，但仍存在。
- Translator、缓存、质量检测和术语库已迁入 LLM 域；`src/core/translate` 只保留兼容转发，等待兼容期结束后删除。
- `/tools/*`、`/pipeline/run` 和 `/pipeline/tasks` 均已删除；公共 HTTP 不再返回路径型兼容结果。

## 5. 功能域当前状态

| 功能域 | 当前状态 |
|---|---|
| 1 工作空间与输入管理 | 已落地，需接入 Workbench 主路径 |
| 2 单任务 pipeline 编排执行器 | 主执行器与桌面正式入口已迁移，旧 execution profile 仅在兼容层保留 |
| 3 统一任务生成与任务队列 | 终态历史已持久化；低并发场景继续使用进程内线程，不建设独立调度器 |
| 4 单步工具执行体系 | 已接入主干，继续收束兼容 DTO |
| 5 模型与运行资源管理 | 已落地；阶段级 readiness 已接入 Workbench，安装链路继续增强 |
| 6 配置与提供方接入管理 | Provider v1 设置、凭据状态、草稿验证和真实连通性测试已落地 |
| 7 字幕与文本资产管理 | 已迁入 `core/subtitles`，残留旧引用已修复 |
| 8 结果资产与产物索引管理 | TaskResult 与 Artifact 公共结构已统一并持久化 |
| 9 结果预览与人工确认 | TaskCenter 已按 Artifact 声明展示主产物与音频预览入口 |
| 10 TTS 引擎管理 | 主干已落地，VoxCPM2 等能力继续扩展 |
| 11 LLM 能力管理 | 主干已落地，模型参数和 provider 默认值仍在调整 |
| 12 ASR 引擎管理 | 主干已落地 |

## 6. 推荐下一步

### P1.5：参数与能力细化

- 根据 CapabilityOption 动态呈现 Provider 私有参数，先覆盖当前主链路实际需要的字段。
- 将 TTS 音色列表和 voice profile 与所选 TTS provider 联动，避免音色与引擎不匹配。
- 完成真实音频的多 Provider 验收，再进入兼容层瘦身。

## 7. 一句话结论

当前不再是“继续替换旧 pipeline 包”的阶段。

当前核心任务是：

> 在能力目录和入队前检查已经打通的基础上，继续补齐动态参数与真实音频验收。
