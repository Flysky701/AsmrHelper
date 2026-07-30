# Provider / Model 接入流程

## 1. 目的

本流程用于新增 ASR、TTS、LLM、separator Provider，或在已有 Provider 下增加模型。

核心原则：

> 上游官方文档和源码用于发现参数；项目锁定版本、Runtime Adapter 和自动测试共同决定 AsmrHelper 最终公开的稳定参数。Server 契约稳定前，不新增 GUI 专用常量或控件。

## 2. 事实源分工

| 事实 | 唯一维护位置 |
|---|---|
| 上游原始 API、参数和限制 | `docs/providers/<provider>.md` |
| 项目实际依赖版本 | `pyproject.toml`、`uv.lock` |
| 上游参数到项目参数的转换 | `src/core/engines/<category>/` Runtime Adapter |
| 客户端可见的能力和参数 | `CapabilityDescriptorService` |
| 模型安装、文件和运行依赖 | `config/models.yaml` |
| 最终可执行性 | `ResourceService` readiness |
| 是否允许进入 GUI | 本流程的 Server Gate 全部通过 |

不得从 GUI 常量、历史文档或上游 `master` 分支单独推导当前可用参数。

## 3. 两类接入路径

### 3.1 新增 Provider

新增 Provider 意味着引入新的运行时实现，例如从 `faster_whisper` 扩展到新的 ASR 后端。

必须依次完成：

1. 上游证据记录。
2. 依赖与版本边界。
3. Runtime Adapter。
4. CapabilityDescriptor。
5. 模型资源目录。
6. Server 参数验证和 readiness。
7. 自动测试。
8. GUI 自动呈现。
9. 真实素材验收。

### 3.2 已有 Provider 新增模型

例如为 `faster_whisper` 增加一个新的模型变体，不应重新实现 Provider。

只需完成：

1. 确认新模型仍使用现有上游 API 和 Adapter。
2. 在 `config/models.yaml` 增加资源项。
3. 在 Provider 的 `supported_models` 增加运行模型 ID。
4. 使用 `capability_models` 显式声明资源项覆盖的运行模型 ID。
5. 补安装、状态、readiness 和最小推理测试。
6. 通过后由现有 GUI 自动显示。

如果新模型需要不同构造函数、依赖组合或参数语义，应按“新增 Provider”处理。

## 4. 固定接入阶段

### Gate 0：上游证据

复制 [Provider 证据模板](../providers/_template.md)，记录：

- 官方仓库和 API 文档。
- 查询日期、tag/commit 和包版本。
- 上游构造函数与执行函数。
- 原始参数、类型、默认值和限制。
- 模型类型、许可证、硬件和系统依赖。
- 已知冲突、弃用项和平台限制。

此阶段只记录上游事实，不直接形成 GUI 参数。

### Gate 1：版本和依赖

- 在 `pyproject.toml` 定义直接依赖或 optional extra。
- 更新 `uv.lock`。
- 明确与其他 extra 的冲突。
- 模型依赖写入 `config/models.yaml`，不得只写在安装脚本中。

### Gate 2：Runtime Adapter

Adapter 只接收 AsmrHelper 已决定支持的参数，并负责：

- 将稳定项目参数转换为上游参数。
- 隔离上游返回值和异常。
- 不静默吞掉未知参数。
- 不从 GUI 读取配置。

每项公开参数必须存在“CapabilityOption → Adapter → 上游调用”的可追踪映射。

### Gate 3：CapabilityDescriptor

每个参数必须明确：

- `name`
- `type`
- `required`
- `default`
- `enum`
- `min/max`
- `advanced`
- `secret`
- 属于 `common_option_schema` 或 `provider_option_schema`

`default_model` 必须包含在 `supported_models` 中。公共参数和 Provider 私有参数不得重名。

### Gate 4：模型资源目录

每个本地模型必须在 `config/models.yaml` 登记：

- Provider/category。
- 安装路径和必要文件。
- 安装策略。
- Python、系统工具和 GPU 条件。
- 支持的安装模式。
- 上游模型名称。

资源项 ID 和运行模型 ID 不一致时，必须使用：

```yaml
capability_models:
  - htdemucs
  - htdemucs_ft
```

禁止依靠“当前只有一个候选模型”的隐式回退建立映射。

### Gate 5：Server 权威验证

Server 必须在任务创建和 `prepare` 阶段验证：

- category、Provider 和 model 组合。
- 参数名称、类型、枚举和范围。
- 必填参数。
- 模型资源与运行依赖。
- 凭据。
- 音色、voice profile 与 TTS Provider 的兼容性。
- 文件和目录类参数。

GUI 预检只负责提前反馈，不能替代该门禁。

### Gate 6：自动测试

最低测试集：

1. 上游参数到 Adapter 的映射测试。
2. 默认参数成功。
3. 合法自定义参数成功。
4. 未知参数、错误类型、越界值被拒绝。
5. 模型缺失和依赖缺失被 readiness 拒绝。
6. Capability 与 `models.yaml` 一致性守卫。
7. HTTP 契约测试。
8. 不加载大型权重的最小 Runtime 测试。

仓库守卫位于：

```text
tests/test_provider_model_onboarding.py
```

新增 Provider 或模型后，该文件失败表示接入步骤不完整，不得通过修改断言绕过。

### Gate 7：GUI

只有 Gate 0 至 Gate 6 完成后，客户端才能消费该能力。

GUI 必须：

- 从 `/capabilities` 获取 Provider、模型和参数。
- 从专用资源接口获取 voice/profile 等动态数据。
- 不维护另一份模型或参数事实源。
- 不向用户显示 Server 尚未验证的实验参数。

### Gate 8：真实验收

验收至少记录：

- 输入素材。
- Provider/model/参数快照。
- 任务状态和阶段日志。
- 主要产物。
- 运行耗时和硬件。
- 已知限制。

通过自动测试但未完成真实素材验收的能力，只能标记为“可执行，未验收”。

## 5. 接入状态

统一使用以下成熟度：

| 状态 | 含义 |
|---|---|
| `discovered` | 已记录上游资料 |
| `declared` | 依赖、Adapter、Capability 和资源目录已登记 |
| `executable` | Server readiness 与最小 Runtime 测试通过 |
| `accepted` | 真实素材验收通过 |
| `default` | 可作为产品默认组合 |

“已下载”“已安装”和“已验收”是不同事实，不得合并描述。

## 6. 提交规则

推荐拆分：

1. `docs: record <provider> upstream evidence`
2. `feat: register <provider/model> runtime and resources`
3. `test: verify <provider/model> contract and readiness`
4. `feat(desktop): expose accepted <provider/model>`
5. `docs: record <provider/model> acceptance`

每个 Gate 完成后提交，避免把未验证的 Server 参数与 GUI 改动混在同一提交中。
