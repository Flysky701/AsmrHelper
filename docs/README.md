# AsmrHelper 文档索引

## 当前权威文档

建议按以下顺序阅读：

1. [后端能力事实清单](roadmap/backend-capability-baseline.md)：区分已实现、环境可执行、真实验收和受限能力。
2. [当前源代码基线](roadmap/current-source-baseline.md)：判断当前代码阶段、验证结果和优先级。
3. [最终验收矩阵（2026-08-07）](roadmap/final-acceptance-2026-08-07.md)：逐项对应本轮 Goal、真实运行和交付证据。
4. [主链路契约 v1](contracts/mainline-v1.md)：桌面端到后台任务的最小稳定流程。
5. [Task Execution V1](contracts/task-execution-v1.md)：统一执行器、生命周期、取消、重提和 Artifact 归属。
6. [数据结构契约 v1](contracts/schemas-v1.md)：请求、任务、错误、执行配置和产物字段。
7. [Provider 与设置契约 v1](contracts/provider-v1.md)：能力、设置、凭据和运行前检查。
8. [Provider / Model 轻量接入流程](contracts/provider-model-onboarding.md)：个人维护项目新增引擎或模型时使用的 Server-first 最小检查清单。
9. [多引擎支持现状](roadmap/multi-engine-status.md)：区分已接线、当前环境可执行和真实主链路验收。
10. [兼容与迁移说明](contracts/compatibility.md)：当前实现与目标契约的差异及迁移顺序。

契约描述目标边界，源代码基线描述当前事实。两者存在差异时，不应猜测；先在兼容说明登记，再通过测试和源代码确认。

## 领域边界

- [领域边界总览](domains/README.md)：输入、任务、Pipeline、Provider、文本资产和产物预览的责任划分。

ASR、TTS、LLM 等能力统一按 Provider 类别扩展，不再分别维护重复的跨层契约。

## 路线图与进度

- [后端能力事实清单](roadmap/backend-capability-baseline.md)
- [当前源代码基线](roadmap/current-source-baseline.md)

以下仍保留在仓库中，但只作为历史快照，不再进入当前执行顺序：

- [2026-07-23 架构审计](roadmap/current-architecture-and-doc-audit-2026-07-23.md)
- [旧总体进度记录](roadmap/overall-progress-status.md)
- [旧 Phase 2 收尾计划](roadmap/phase-2-legacy-core-replacement.md)
- [旧主链路检查清单](roadmap/mainline-refactor-checklist.md)
- [重构恢复简报（2026-07-18）](archived/roadmap/restart-briefing-2026-07-18.md)

## 设计草案

- [桌面端 UI 重设计蓝图](designs/desktop-ui-redesign-blueprint.md)
- [模型资产管理需求草案](designs/model-asset-management-requirements.md)
- [模型资产元数据与安装契约草案](designs/model-asset-schema-design.md)
- [轻量结果预览方案](designs/lightweight-result-preview.md)

设计草案用于讨论后续能力，不自动代表已经实现。

## 历史归档

- [归档说明](archived/README.md)
- [历史契约](archived/contracts/)
- [历史领域文档](archived/domains/)
- [历史路线图](archived/roadmap/)
- [已执行计划](archived/plans/)
- [历史排查日志](archived/logs/)

归档内容只用于追溯，不再作为当前开发入口。
