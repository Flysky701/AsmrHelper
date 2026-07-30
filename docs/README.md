# AsmrHelper 文档索引

## 当前权威文档

建议按以下顺序阅读：

1. [当前架构与文档审计](roadmap/current-architecture-and-doc-audit-2026-07-23.md)：项目现状、已验证问题和优先级。
2. [主链路契约 v1](contracts/mainline-v1.md)：桌面端到后台任务的最小稳定流程。
3. [数据结构契约 v1](contracts/schemas-v1.md)：请求、任务、错误、执行配置和产物字段。
4. [Provider 与设置契约 v1](contracts/provider-v1.md)：能力、设置、凭据和运行前检查。
5. [Provider / Model 轻量接入流程](contracts/provider-model-onboarding.md)：个人维护项目新增引擎或模型时使用的 Server-first 最小检查清单。
6. [多引擎支持现状](roadmap/multi-engine-status.md)：区分已接线、当前环境可执行和真实主链路验收。
7. [兼容与迁移说明](contracts/compatibility.md)：当前实现与目标契约的差异及迁移顺序。
8. [当前源代码基线](roadmap/current-source-baseline.md)：判断“代码目前已经做到什么”的事实依据。

契约描述目标边界，源代码基线描述当前事实。两者存在差异时，不应猜测；先在兼容说明登记，再通过测试和源代码确认。

## 领域边界

- [领域边界总览](domains/README.md)：输入、任务、Pipeline、Provider、文本资产和产物预览的责任划分。

ASR、TTS、LLM 等能力统一按 Provider 类别扩展，不再分别维护重复的跨层契约。

## 路线图与进度

- [当前架构与文档审计（2026-07-23）](roadmap/current-architecture-and-doc-audit-2026-07-23.md)
- [当前源代码基线](roadmap/current-source-baseline.md)
- [总体进度状态](roadmap/overall-progress-status.md)
- [Phase 2 后段收尾计划](roadmap/phase-2-legacy-core-replacement.md)
- [主链路重构检查清单](roadmap/mainline-refactor-checklist.md)
- [重构恢复简报（2026-07-18，历史快照）](archived/roadmap/restart-briefing-2026-07-18.md)

路线图是阶段记录。日期较早的内容若与当前架构审计冲突，以较新的实测结果为准。

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
