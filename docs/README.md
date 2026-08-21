# AsmrHelper 文档索引

## 当前权威文档

建议按以下顺序阅读：

1. [当前源码基线](roadmap/current-source-baseline.md)：当前分支源码、入口、删除项、限制和验证状态。
2. [后端能力事实清单](roadmap/backend-capability-baseline.md)：区分已实现、环境可执行、真实验收、已接线和受限能力。
3. [主链路契约 v1](contracts/mainline-v1.md)：桌面端到后台任务的最小稳定流程。
4. [Task Execution V1](contracts/task-execution-v1.md)：统一执行器、生命周期、取消、重提和 Artifact 归属。
5. [数据结构契约 v1](contracts/schemas-v1.md)：请求、任务、错误、执行配置和产物字段。
6. [Provider 与设置契约 v1](contracts/provider-v1.md)：能力、设置、凭据和运行前检查。
7. [Provider / Model 轻量接入流程](contracts/provider-model-onboarding.md)：新增引擎或模型时使用的最小检查清单。
8. [多引擎支持现状](roadmap/multi-engine-status.md)：区分已接线、当前环境可执行和真实主链路验收。
9. [运行环境隔离进度](roadmap/runtime-environment-isolation-todo.md)：记录隔离运行时的当前边界和剩余 TODO。
10. [兼容与迁移说明](contracts/compatibility.md)：当前实现与目标契约的差异及迁移顺序。

契约描述目标边界，源码基线描述当前事实。两者存在差异时，不应猜测；先在兼容说明登记，再通过测试和源代码确认。

## 领域边界

- [领域边界总览](domains/README.md)：输入、任务、Pipeline、Provider、文本资产和产物预览的责任划分。

ASR、TTS、LLM 等能力统一按 Provider 类别扩展，不再分别维护重复的跨层契约。

## 路线图与进度

- [当前源码基线](roadmap/current-source-baseline.md)
- [后端能力事实清单](roadmap/backend-capability-baseline.md)
- [多引擎支持现状](roadmap/multi-engine-status.md)
- [运行环境隔离进度](roadmap/runtime-environment-isolation-todo.md)

2026-08-21 已将阶段性计划、旧进度快照、旧架构审计、旧验收矩阵和根目录重构草案移入 [历史路线图](archived/roadmap/)。它们保留用于追溯，不再参与当前执行顺序。

## 设计草案

- [桌面端 UI 重设计蓝图](designs/desktop-ui-redesign-blueprint.md)
- [模型资产管理需求草案](designs/model-asset-management-requirements.md)
- [模型资产元数据与安装契约草案](designs/model-asset-schema-design.md)
- [轻量结果预览方案](designs/lightweight-result-preview.md)

设计草案用于讨论后续能力，不自动代表已经实现；草案中的 API 和字段必须以当前契约和源码为准。

## 历史归档

- [归档说明](archived/README.md)
- [历史契约](archived/contracts/)
- [历史领域文档](archived/domains/)
- [历史路线图](archived/roadmap/)
- [已执行计划](archived/plans/)
- [历史排查日志](archived/logs/)

归档内容只用于追溯，不再作为当前开发入口。
