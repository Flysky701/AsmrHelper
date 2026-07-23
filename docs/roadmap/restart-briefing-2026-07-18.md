# 重构恢复简报（历史快照）

日期：2026-07-18  
适用分支：`refactor/re-design`  
盘点基线：`3bd5c4a`

> 本文保留 2026-07-18 的恢复判断。2026-07-23 已完成 Python 测试、前端构建、Tauri release build 与实际启动验证；当前执行请优先阅读 [当前架构与文档审计](current-architecture-and-doc-audit-2026-07-23.md) 和 [当前源码基线](current-source-baseline.md)。

## 结论

项目并非处于“从零重构”或“继续删除旧目录”的阶段，而是处于 **Phase 2 后段收尾**：新 core 主干、桌面端第一轮重设计、模型资源管理和引擎注册体系均已存在并已经接线；接下来的重心是让这些部分遵循同一份主链路契约，形成可稳定验证的产品路径。

本轮恢复工作应只保护并打磨下面这条主链路：

```text
Workbench 选择输入与参数
  -> 创建 Session 与 Pipeline Task
  -> Pipeline 执行
  -> TaskCenter 展示显式状态与阶段
  -> Artifact 结果
  -> Preview / 播放 / 人工确认
```

## 已具备的能力

| 范围 | 当前事实 |
| --- | --- |
| 桌面端 | `desktop/` 是 Tauri + React + Vite 应用。Workbench、TaskCenter、EnginesResources、Settings、SubtitleWorkshop 均已存在；2026-05-27 完成一轮 Workbench/TaskCenter UI 重设计。 |
| 后端入口 | Python + FastAPI。已提供 workspace、input、session、task、artifact、preview、engine/resource 等 HTTP 路由。 |
| Pipeline | 主执行器已迁至 `src/core/orchestration/pipeline/`，直接消费 separator、ASR、LLM、TTS、mixer runtime。 |
| 任务与会话 | `src/core/sessions/` 和 `src/core/tasks/` 已存在，`POST /sessions` 与 `POST /tasks` 已可用；任务仍是进程内轻量系统，并非持久化队列。 |
| 引擎与模型 | ASR、LLM、TTS、separator registry/runtime 已是主路径组成部分。模型安装支持异步进度及按需 Python 可选依赖；TTS 已包含 Kokoro、VoxCPM2 等扩展。 |
| 文本与结果 | 字幕/脚本能力集中在 `src/core/subtitles/`；任务产物、结果与轻量预览 API 已存在。 |

## 尚未收束的关键断点

1. **桌面入口仍走兼容路径。** Workbench 通过 `desktop/src/api/pipeline.ts` 调用 `POST /pipeline/run`。该路由虽然会在后端内部创建 session/task，但客户端尚未以 `POST /sessions -> POST /tasks` 为正式主路径。
2. **执行参数仍偏旧结构。** `PipelineService.create_pipeline_task_spec()` 生成 `pipeline + stages + mix`；planner 尚未优先消费契约定义的 `profile_version + stages + profiles`。
3. **任务状态不足以支撑驾驶舱。** `TaskStatus` 目前没有显式 `stage`、`error`、`created_at`、`started_at`、`finished_at`、`artifact_set_id`。TaskCenter 仍需部分依赖 `message/detail/progress` 推断阶段。
4. **旧路径仍有运行时风险。** `src/app/services/script_subtitle_service.py` 仍延迟导入已删除的 `src.core.script_to_subtitle`；实际调用将触发 `ModuleNotFoundError`。
5. **兼容层尚未完成瘦身。** `ModelManager`、`core.translate` 和部分 app service 仍承担旧字段映射或历史入口兼容，不能再成为新能力的默认依赖。

## 建议恢复顺序

| 优先级 | 工作切片 | 完成标志 |
| --- | --- | --- |
| P0 | 修复字幕服务残留 import，并补回归测试 | 旧路径不再可被调用，字幕域测试覆盖真实入口 |
| P1 | 落实字段与基础设施契约，统一 CapabilityOption、RuntimeEvent、模型字段和 provider_options | 新 provider 参数不再扩张 pipeline 顶层字段 |
| P2 | 让 PipelineService 与 planner 优先支持新 ExecutionProfile，同时保留 `/pipeline/run` 的适配 | 新旧请求均可执行，但只有新契约定义新字段 |
| P3 | 补齐 TaskStatus、任务 API 和 executor 的阶段回写 | TaskCenter 不再猜测阶段，失败可定位且有时间线 |
| P4 | 将 Workbench 迁至 session + task；让 TaskCenter 消费 tasks + artifacts + preview | 客户端获得稳定 server task_id 与正式结果入口 |
| P5 | 继续压薄兼容 app service 与 deprecated core 层 | 新代码不新增对 ModelManager/core.translate 的直接依赖 |

## 当前不应扩张的范围

- 不恢复已删除的 `src/gui/`、`src/core/pipeline/` 或旧字幕包。
- 不在此阶段重做音频算法、跨进程持久化队列或复杂人工审校编辑器。
- 不优先做与主链路无关的页面精修或复杂动效。

## 文档使用顺序

开始实现前，按以下顺序读取：

1. [当前源码基线](current-source-baseline.md)：当前事实、验证限制与已知问题。
2. [主链路契约 v1](../contracts/mainline-v1.md) 与 [数据结构契约 v1](../contracts/schemas-v1.md)：当前业务主链路和跨模块字段定义。
3. [Provider 与设置契约 v1](../contracts/provider-v1.md) 与 [兼容说明](../contracts/compatibility.md)：能力边界和旧实现迁移规则。
4. [Phase 2 后段收尾计划](phase-2-legacy-core-replacement.md)：各切片的具体范围和验收标准。
5. 按改动所属范围再读 `docs/domains/` 和 `docs/designs/`，归档目录只用于追溯历史。

## 本次验证与环境状态

- `python -m compileall src`：2026-07-18 通过。
- pytest：未在本机重新执行。默认 Python 3.14 未安装 pytest；离线 `uv` 解析因未缓存 CUDA PyTorch 包失败。
- 桌面构建：2026-07-19 已通过。使用 `E:\Dependencies\nodejs` 的 Node v24.18.0、npm v11.16.0，`npm ci` 成功安装 92 个依赖，`npm run build`（`tsc -b && vite build`）成功。

因此，恢复开发前的首要环境动作是用锁定依赖建立项目 Python 测试环境并执行 `python -m pytest`。桌面端依赖安装和生产构建已经复验通过；本节的测试环境限制不代表仓库当前已知有新的测试或构建失败。
