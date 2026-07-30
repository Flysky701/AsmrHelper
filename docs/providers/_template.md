# Provider 简要记录：`<provider>`

仅在新增 Provider，或上游存在容易踩坑的版本、参数和依赖差异时使用本模板。已有 Provider 增加普通 Model 不必复制本文件。

## 基本信息

| 项目 | 内容 |
|---|---|
| category / provider | `<asr/tts/llm/separator>` / `<provider_id>` |
| 官方来源 | `<repository-or-api-doc-url>` |
| 查询日期 | `<YYYY-MM-DD>` |
| 项目使用版本 | `<package==version>` |
| 上游入口 | `<constructor / execute method>` |

## 项目参数映射

只列 AsmrHelper 准备公开的参数。

| 项目参数 | 上游参数 | 默认值 | 转换或限制 |
|---|---|---|---|
| `<name>` | `<upstream_name>` | `<default>` | `<mapping-or-limit>` |

## 模型与依赖

- Model ID：`<model_id>`
- 本地资源 ID：`<catalog_id-or-not-applicable>`
- 关键依赖：`<python-package/system-tool/model-file>`
- 已知限制：`<platform/version/hardware/conflict>`

## 验证

- [ ] 上游参数已与当前锁定版本核对。
- [ ] Server 参数校验和 readiness 通过。
- [ ] 一个真实样本运行成功。
