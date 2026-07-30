# Provider 证据：<provider>

## 基本信息

| 字段 | 内容 |
|---|---|
| category | `<asr/tts/llm/separator>` |
| provider | `<stable_provider_id>` |
| 官方仓库 | `<url>` |
| 官方 API 文档 | `<url>` |
| 查询日期 | `<YYYY-MM-DD>` |
| 上游 tag/commit | `<tag-or-commit>` |
| Python 包 | `<distribution-name>` |
| 项目锁定版本 | `<version-or-range>` |
| 许可证 | `<license>` |

## 上游 API

### 构造函数

```text
<signature>
```

### 执行函数

```text
<signature>
```

## 参数映射

| AsmrHelper 参数 | 上游参数 | 类型 | 默认值 | 转换/限制 | Adapter 已消费 |
|---|---|---|---|---|---|
| `<name>` | `<upstream_name>` | `<type>` | `<default>` | `<mapping>` | `<yes/no>` |

只允许 `Adapter 已消费=yes` 且测试通过的参数进入 CapabilityDescriptor。

## 模型与资源

| 运行模型 ID | 资源项 ID | 上游模型 | 安装方式 | 硬件要求 |
|---|---|---|---|---|
| `<capability_model>` | `<catalog_id>` | `<upstream_name>` | `<strategy>` | `<requirements>` |

## 已知限制

- `<platform/version/conflict/deprecation>`

## 验证记录

| Gate | 状态 | 证据 |
|---|---|---|
| 上游证据 | pending | |
| 依赖与版本 | pending | |
| Runtime Adapter | pending | |
| CapabilityDescriptor | pending | |
| 模型资源目录 | pending | |
| Server 验证与 readiness | pending | |
| 自动测试 | pending | |
| GUI | pending | |
| 真实素材验收 | pending | |
