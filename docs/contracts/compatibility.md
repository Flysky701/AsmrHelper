# 契约兼容与迁移说明

> 本文记录“当前实现”与“目标契约”的差异。目标契约见同目录其他 v1 文档；历史设计不再作为实现依据。

## 1. 当前主要差异

| 项目 | 当前实现或旧文档 | v1 目标 |
| --- | --- | --- |
| Pipeline 创建 | 仅支持 `POST /pipeline-runs` 一次提交并返回 `202` | `POST /pipeline-runs` 一次提交并立即返回 `202` |
| 执行配置 | HTTP 仅接受统一 `StageProfile` | 每个阶段使用统一 `StageProfile` |
| 进度范围 | 旧示例同时出现 `42` 和 `0.42` | 固定 `0.0` 到 `1.0` |
| TTS 标识 | `edge` 与 `edge_tts` 混用 | `edge` |
| 语言代码 | `zh` 与 `zh-CN` 混用 | 当前稳定使用 `ja`、`zh`、`en` |
| 设置写入 | 后端使用 `{ "settings": ... }`，桌面端曾存在直传或错误方法 | 统一 `PUT` 和 `{ "settings": ... }` |
| 凭据读取 | 掩码字符串兼作状态 | 独立 `credential_configured` |
| Provider 测试 | 部分实现只检查字段是否存在 | 执行真实连通性或最小推理测试 |
| 错误展示 | 已按后端 `stage` 和结构化错误展示 | 展示完整 `TaskError` 和真实阶段 |
| 任务执行 | 已移出 API 请求线程；SQLite 保留终态历史和产物索引，重启时删除未完成任务 | 低并发场景保留进程内线程，API 只管理任务；暂不建设独立调度器 |
| 产物 | 存在 `artifact_set_id` 等内部结构 | 公共结果以 `primary_artifact_id` 和 `artifacts` 为准 |
| 运行事件 | 旧 SSE 推送整份 TaskStatus | SSE 推送单任务递增 RuntimeEvent；TaskStatus 仍是唯一状态事实 |

## 2. 旧接口策略

- 只支持当前 V1 客户端；`/pipeline/run`、`/pipeline/tasks`、`/pipeline-runs/start`、`/pipeline-runs/execute`、同步 `POST /tool-runs` 和 `/tools/*` 已删除。
- `POST /pipeline-runs` 不再接受平铺 Pipeline 参数，只接受 `input/output/execution_profile`。
- 公共结果固定为 TaskResult；HTTP 响应不得出现 `files/primary_output`。
- 内部旧 DTO 或解析分支不得成为新能力入口，并应继续逐步移除。

### 2.1 当前保留边界与删除条件

| 兼容项 | 当前真实用途 | 删除条件 |
| --- | --- | --- |
| Python core 旧入口 | `src.core.model_manager` 与 `src.core.translate` 已删除；翻译、字幕和模型服务分别由各领域 registry 提供 | 已完成；负向架构测试防止旧入口复活 |
| 路径型 `primary_output/files` | 仅存在于内部执行器模型 | 内部执行器全面改用 ArtifactRecord 后删除 |

## 3. 迁移顺序

1. 后端增加 v1 请求和统一错误模型，并删除旧 HTTP 输入。已完成。
2. 将 Pipeline 执行移出 API 请求线程，确保创建立即返回。已完成进程内后台执行。
3. 桌面端切换到权威任务查询、取消、重试和结果接口。已完成。
4. 修正设置方法、响应包络、凭据状态和 Provider 测试。已完成。
5. 删除旧接口，路径型字段只允许暂留内部。已完成公共接口部分。

2026-07-23 已验证：Workbench 单次提交、后台接管、显式阶段、协作取消、新任务重试和完整错误消息均已落码。

2026-07-23 已确认并落码重启策略：终态任务、TaskSpec 和 Artifact 索引存入 SQLite；未完成任务在下次加载时删除；桌面端启动后载入历史并按需查询产物；历史任务不直接重试，需从 Workbench 重新提交。全量测试 `139 passed`，桌面端构建通过。

2026-07-23 已完成 StageProfile 收敛：Workbench 直接提交嵌套 `input/output/execution_profile`；每个阶段统一携带 `enabled/provider/model/options/provider_options`；Planner 直接消费该结构。当时旧平铺请求仍有兼容回归，现已删除。混音延迟统一为 `tts_delay_ms`。全量测试 `141 passed`。

2026-07-28 已完成内部执行配置收敛：CLI 与 batch 的平铺参数在 PipelineService 边界统一转换为 StageProfile V1，并在任务创建及 `prepare` 阶段执行同一套 readiness；planner 已拒绝旧 `pipeline/stages/mix` profile，旧 HTTP 路由和旧模块路径的负向架构测试继续保留。

2026-07-23 已完成 Provider 设置收敛：桌面端统一使用 `PUT` 与 `{ "settings": ... }`；读取仅返回 `credential_configured`，不返回原文或伪密钥；空密钥保持原值；Provider 测试会使用当前草稿配置执行真实轻量请求，并返回稳定错误代码。全量测试 `148 passed`，桌面端构建通过。

2026-07-24 已完成结果语义收敛：Task、Pipeline 和 Tool 结果统一为 `task_id + primary_artifact_id + artifacts + warnings`；Artifact 公共字段统一为 `type/primary/preview`；TaskCenter 改查权威结果接口，不再从文件扩展名或 `files` 映射猜测主产物和预览能力。全量测试 `151 passed`，桌面端构建通过。

2026-07-24 已完成 CapabilityOption 与模型可执行状态收敛：Option 固定返回枚举、范围、高级和敏感标记；ModelStatus 分离安装状态与 `executable`，并明确返回 Python 依赖、系统工具、GPU、凭据或权重问题。全量测试 `156 passed`，桌面端构建通过。

2026-07-24 已完成 RuntimeEvent 收敛：任务生命周期生成单任务递增事件，`after_sequence` 支持续读，SSE 和 TaskCenter 日志消费统一结构；模型安装事件明确携带 `operation/model_id/state/progress`。同时移除 TTS 音频预处理对旧翻译包中字幕工具的反向依赖。全量测试 `160 passed`，桌面端构建通过。

2026-07-24 已完成翻译核心迁移：Translator、翻译缓存、质量检测和术语库迁入 `core.engines.llm`；繁简映射迁入 `core.subtitles`。当时保留了 `ModelManager` 与 `core.translate` 弃用转发；2026-08-19 经仓库引用审计后两者均已删除，core 根导出同步收口，并增加负向架构测试。

2026-07-24 曾完成同步执行结果收敛：CLI、当时的 `POST /pipeline-runs/execute` 和 `POST /tool-runs` 都从权威 Artifact 索引返回或展示 TaskResult。两条同步 HTTP 执行入口已在 2026-08-07 删除；正式产品只保留创建即提交与结果查询。

2026-07-24 已完成工具接口任务化：新增 `POST /tool-runs/tasks` 创建工具任务，桌面 `toolsApi` 改用任务创建、执行和 TaskResult 查询；确认没有活跃页面使用旧同步接口后，删除 `/tools/*` 五个路由及旧响应类型。全量测试 `168 passed`，HTTP 环境验证为 90 条路由，桌面构建通过。

2026-07-24 已结束旧客户端兼容：删除 `/pipeline/run`、`/pipeline/tasks`、旧 PipelineRun 请求/响应结构，并取消 `/pipeline-runs` 对平铺请求的联合解析。HTTP 只接受 V1 嵌套 StageProfile。全量测试 `166 passed`，HTTP 环境验证为 88 条路由，桌面构建通过。

## 4. 回归基线

至少覆盖：

- 默认参数启动一条完整任务；
- 缺少 Python 依赖时定位到实际阶段和依赖名；
- TTS 未返回音频时报告 `tts / PROVIDER_RESPONSE_INVALID`；
- 单任务不会永久停留在队列；
- 取消与重试不会覆盖原任务；
- 重启后终态历史和产物索引存在，未完成任务不存在；
- 设置保存后可读取脱敏状态，并能执行 Provider 实测；
- 最终结果存在一个明确主产物。

## 5. 历史资料

旧契约与旧领域设计已移至：

- [历史契约](../archived/contracts/)
- [历史领域文档](../archived/domains/)

历史资料只用于追溯设计来源。发生冲突时，以当前 v1 契约和源代码基线为判断依据。
