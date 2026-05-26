# AsmrHelper 文档索引

## 契约系统

系统总体契约由以下文档共同定义：

- [功能架构总览](contracts/functional-architecture-overview.md) — 12 个功能域的边界、分层与依赖关系
- [API 契约总表](contracts/api-contract.md) — 每个功能域的主接口、兼容接口与长期方向
- [Service 映射总表](contracts/service-layer-mapping.md) — 现有 service 到功能域的归属、拆分与迁移策略
- [字段契约约束 V1](contracts/field-contracts-v1.md) — Task、Service、Capability、TTS、Artifact 等横向字段约束
- [基础设施契约 V1](contracts/infrastructure-contracts-v1.md) — 日志事件、模型字段、CapabilityOption、高级参数与 RuntimeBinding 边界
- [主链路 V1 契约](contracts/mainline-v1-contract.md) — 当前阶段 Workbench、TaskCenter、Artifact、Preview 的最小稳定执行契约
- [主链路 V1 数据参数契约](contracts/mainline-v1-data-parameters.md) — 当前阶段 Session、TaskSpec、ExecutionProfile、RuntimeBinding 的字段定义

前三份文档是系统级基线，主链路 V1 契约与数据参数契约是当前阶段分步执行的直接基线。

建议阅读顺序：

1. 先读 [主链路 V1 契约](contracts/mainline-v1-contract.md)，确认当前要落地的端到端闭环。
2. 再读 [字段契约约束 V1](contracts/field-contracts-v1.md)，确认 Task、Service、Capability、TTS、Artifact 等横向字段规则。
3. 再读 [基础设施契约 V1](contracts/infrastructure-contracts-v1.md)，确认日志事件、模型资源字段、能力参数 schema、高级参数和运行绑定边界。
4. 再读 [主链路 V1 数据参数契约](contracts/mainline-v1-data-parameters.md)，确认主链路字段、默认值、旧字段映射和敏感参数边界。
5. 再读 [API 契约总表](contracts/api-contract.md)，确认主接口和兼容接口边界。
6. 需要拆 service 或迁移旧逻辑时，再读 [功能架构总览](contracts/functional-architecture-overview.md) 和 [Service 映射总表](contracts/service-layer-mapping.md)。

## 功能域详细计划

每个功能域的 V1 边界、职责与实现约束：

| 编号 | 文档 | 所属层 |
|------|------|--------|
| 01 | [工作空间与输入管理](domains/01-workspace-input-management.md) | 输入与任务控制层 |
| 02 | [单任务流水线编排执行器](domains/02-pipeline-executor.md) | 业务执行与资产层 |
| 03 | [统一任务生成与任务队列](domains/03-task-generation-queue.md) | 输入与任务控制层 |
| 04 | [单步工具执行体系](domains/04-tool-execution.md) | 业务执行与资产层 |
| 05 | [模型与运行资源管理](domains/05-model-runtime-management.md) | 基础控制层 |
| 06 | [配置与提供方接入管理](domains/06-configuration-provider-management.md) | 基础控制层 |
| 07 | [字幕与文本资产管理](domains/07-subtitle-text-asset.md) | 业务执行与资产层 |
| 08 | [结果资产与产物索引管理](domains/08-result-artifact-index.md) | 业务执行与资产层 |
| 09 | [结果预览、浏览与人工校对](domains/09-preview-review.md) | 结果消费层 |
| 10 | [TTS 引擎管理与扩展能力管理](domains/10-tts-engine-management.md) | 引擎能力域层 |
| 11 | [LLM 能力管理与衍生操作管理](domains/11-llm-capability-management.md) | 引擎能力域层 |
| 12 | [ASR 引擎管理与扩展能力管理](domains/12-asr-engine-management.md) | 引擎能力域层 |

## 进行中的设计方案

- [桌面端 UI 重设计蓝图](designs/desktop-ui-redesign-blueprint.md)
- [模型资产管理需求草案](designs/model-asset-management-requirements.md)
- [模型资产元数据与安装契约草案](designs/model-asset-schema-design.md)
- [轻量结果预览方案](designs/lightweight-result-preview.md)

## 路线图与进度

- [当前源码基线](roadmap/current-source-baseline.md) — 当前进度判断的第一事实源，优先于旧计划
- [总体进度状态](roadmap/overall-progress-status.md)
- [Phase 2 后段收尾计划](roadmap/phase-2-legacy-core-replacement.md)
- [主链路重构检查清单](roadmap/mainline-refactor-checklist.md)

## 归档

已执行完毕或脱离当前开发环境的文档。归档内容只保留历史背景，不再作为当前实现状态或执行优先级的基准：

- [已执行计划](archived/plans/) — 切片实施计划、迁移清单、里程碑快照
- [历史排查日志](archived/logs/) — Git 恢复、前端闪退、连接修复等一次性排障记录
