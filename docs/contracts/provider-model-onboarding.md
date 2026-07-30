# Provider / Model 轻量接入流程

本流程面向个人维护项目，目标是避免参数猜测和跨层不一致，而不是增加审批或文档负担。

核心原则：

- 先确认上游 API，再修改 Server。
- Server 能独立运行后，客户端才消费能力描述。
- 只记录项目实际支持的参数，不复制整份上游文档。
- 自动检查只保留能防止真实运行错误的部分。

## 1. 改动位置

| 内容 | 位置 |
|---|---|
| 上游 API、版本和特殊限制 | `docs/providers/<provider>.md`，仅新 Provider 或存在特殊差异时创建 |
| 运行时适配与参数转换 | `src/core/engines/<category>/` |
| 客户端可见的 Provider、Model 和参数 | `CapabilityDescriptorService` |
| 本地模型安装与运行依赖 | `config/models.yaml` |
| 运行前检查 | `ResourceService` readiness |
| 通用一致性检查 | `tests/test_provider_model_onboarding.py` |

上游说明用于确认可用参数；AsmrHelper 实际公开的参数以当前锁定版本、Runtime Adapter 和测试为准。

## 2. 已有 Provider 增加 Model

模型仍使用相同上游 API 和 Adapter 时，只需：

1. 在 Provider 的 `supported_models` 中加入运行模型 ID。
2. 本地模型在 `config/models.yaml` 登记资源；资源 ID 与运行模型 ID 不同时，用 `capability_models` 显式映射。
3. 运行通用一致性测试，并用一个真实样本验证。

不需要复制 Provider 文档、增加新 Adapter 或单独设计 GUI。客户端应从 `/capabilities` 自动取得模型列表。

如果新模型需要不同的依赖、构造方式或参数语义，则按“新增 Provider”处理。

## 3. 新增 Provider

### 第一步：确认上游事实

使用 [简要记录模板](../providers/_template.md) 保存以下信息：

- 官方仓库或 API 文档；
- 本项目使用的包版本；
- 构造和执行入口；
- 准备公开的关键参数及限制。

只记录会影响实现和维护的内容。

### 第二步：完成 Server

- 增加必要依赖和 Runtime Adapter。
- 在 `CapabilityDescriptorService` 声明 Provider、Model、默认值和参数范围。
- 本地模型在 `config/models.yaml` 登记资源与运行依赖。
- readiness 能发现缺失的模型、Python 包、系统工具或凭据。
- Server 拒绝未知参数、错误类型和非法范围。

参数链路应能追踪为：

```text
Capability option -> Runtime Adapter -> upstream API
```

### 第三步：验证并开放客户端

- 运行 `tests/test_provider_model_onboarding.py`。
- 为特殊参数转换补一个聚焦测试。
- 使用一个真实输入完成最小推理。
- 客户端优先复用 `/capabilities` 自动呈现；只有现有 schema 无法表达时才增加专用控件。

## 4. 最小完成标准

接入只判断三个状态：

| 状态 | 判定 |
|---|---|
| 可发现 | 上游来源和关键参数已确认 |
| 可运行 | Server 参数校验、readiness 和最小推理通过 |
| 已验收 | 真实素材运行成功，产物可用 |

默认 Provider 或 Model 必须达到“已验收”。“已下载”不等于“可运行”或“已验收”。

## 5. 最小检查清单

新增或修改 Provider / Model 时确认：

- [ ] Provider、Model ID 与能力描述一致。
- [ ] 默认 Model 包含在 `supported_models` 中。
- [ ] 本地模型存在明确的 `capability_models` 资源映射。
- [ ] 参数名称、类型、默认值和范围有效。
- [ ] Adapter 实际消费公开参数，未知参数不会被静默忽略。
- [ ] readiness 能报告关键依赖缺失。
- [ ] 通用测试和一个真实样本通过。

一次小型接入可以使用一个提交；只有改动较大或需要独立回退时再拆分。
