# 契约兼容与迁移说明

> 本文记录“当前实现”与“目标契约”的差异。目标契约见同目录其他 v1 文档；历史设计不再作为实现依据。

## 1. 当前主要差异

| 项目 | 当前实现或旧文档 | v1 目标 |
| --- | --- | --- |
| Pipeline 创建 | Workbench 已使用 `POST /pipeline-runs` 一次提交并返回 `202`；`/pipeline/run` 仅保留兼容 | `POST /pipeline-runs` 一次提交并立即返回 `202` |
| 执行配置 | Workbench 和 `/pipeline-runs` 已使用统一 `StageProfile`；旧 `stages + profiles` 与平铺参数由兼容层解析 | 每个阶段使用统一 `StageProfile` |
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

- `/api/v1/pipeline/run` 暂作为兼容入口，内部转换为新的创建请求。
- 旧 `ExecutionProfile` 的 `stages + profiles` 在入口处归一化为新的 `StageProfile`。
- `edge_tts` 在兼容层映射为 `edge`。
- 旧的整数百分比只在兼容输入中接受，输出始终为 `0.0` 到 `1.0`。
- 旧任务和产物字段可以继续存储，但不得要求新桌面端依赖。

兼容层应有明确删除条件；不得继续向旧结构增加新能力。

### 2.1 当前保留边界与删除条件

| 兼容项 | 当前真实用途 | 删除条件 |
| --- | --- | --- |
| `/api/v1/pipeline/run` | 旧客户端和兼容回归；Workbench、CLI 已不再调用 | 发布一个明确不再支持旧客户端的版本 |
| `src.core.model_manager` | 仅支持显式旧导入并发出 DeprecationWarning；主服务使用各引擎 registry | 仓库外调用方完成迁移，且兼容期结束 |
| `src.core.translate` | 已只保留 Translator、缓存、术语和字幕工具的弃用转发；实现分别位于 `core.engines.llm` 与 `core.subtitles` | 兼容期结束且仓库外旧导入完成迁移 |
| `src.core.translate` 中的字幕工具转发 | 只服务仓库外旧导入；活跃 TTS 预处理已改用 `src.core.subtitles` | 兼容期结束且外部调用迁移完成 |
| 路径型 `primary_output/files` | 内部执行器与 `/pipeline/run`、`/tools/*` 旧同步响应 | 旧客户端与桌面工具交互迁入任务创建、状态查询和 TaskResult 后，发布移除版本 |

## 3. 迁移顺序

1. 后端先增加 v1 请求归一化和统一错误模型。已完成；旧结构仅由兼容入口转换。
2. 将 Pipeline 执行移出 API 请求线程，确保创建立即返回。已完成进程内后台执行。
3. 桌面端切换到权威任务查询、取消、重试和结果接口。已完成。
4. 修正设置方法、响应包络、凭据状态和 Provider 测试。已完成。
5. 完成主链路回归后，再删除旧接口和旧字段。

2026-07-23 已验证：Workbench 单次提交、后台接管、显式阶段、协作取消、新任务重试和完整错误消息均已落码。

2026-07-23 已确认并落码重启策略：终态任务、TaskSpec 和 Artifact 索引存入 SQLite；未完成任务在下次加载时删除；桌面端启动后载入历史并按需查询产物；历史任务不直接重试，需从 Workbench 重新提交。全量测试 `139 passed`，桌面端构建通过。

2026-07-23 已完成 StageProfile 收敛：Workbench 直接提交嵌套 `input/output/execution_profile`；每个阶段统一携带 `enabled/provider/model/options/provider_options`；Planner 直接消费该结构，旧平铺请求继续有回归测试。混音延迟统一为 `tts_delay_ms`。全量测试 `141 passed`。

2026-07-23 已完成 Provider 设置收敛：桌面端统一使用 `PUT` 与 `{ "settings": ... }`；读取仅返回 `credential_configured`，不返回原文或伪密钥；空密钥保持原值；Provider 测试会使用当前草稿配置执行真实轻量请求，并返回稳定错误代码。全量测试 `148 passed`，桌面端构建通过。

2026-07-24 已完成结果语义收敛：Task、Pipeline 和 Tool 结果统一为 `task_id + primary_artifact_id + artifacts + warnings`；Artifact 公共字段统一为 `type/primary/preview`；TaskCenter 改查权威结果接口，不再从文件扩展名或 `files` 映射猜测主产物和预览能力。全量测试 `151 passed`，桌面端构建通过。

2026-07-24 已完成 CapabilityOption 与模型可执行状态收敛：Option 固定返回枚举、范围、高级和敏感标记；ModelStatus 分离安装状态与 `executable`，并明确返回 Python 依赖、系统工具、GPU、凭据或权重问题。全量测试 `156 passed`，桌面端构建通过。

2026-07-24 已完成 RuntimeEvent 收敛：任务生命周期生成单任务递增事件，`after_sequence` 支持续读，SSE 和 TaskCenter 日志消费统一结构；模型安装事件明确携带 `operation/model_id/state/progress`。同时移除 TTS 音频预处理对旧翻译包中字幕工具的反向依赖。全量测试 `160 passed`，桌面端构建通过。

2026-07-24 已完成翻译核心迁移：Translator、翻译缓存、质量检测和术语库迁入 `core.engines.llm`；繁简映射迁入 `core.subtitles`；LLM registry、ModelManager 内部构造和 core 根导出均使用新实现路径。`core.translate` 只保留带弃用提示的兼容转发。全量测试 `163 passed`。

2026-07-24 已完成执行结果收敛：CLI、`POST /pipeline-runs/execute` 和 `POST /tool-runs` 都从权威 Artifact 索引返回或展示 TaskResult；不再读取 `primary_output/files`。路径型字段仅保留在明确标注的 `/pipeline/run` 与 `/tools/*` 同步兼容路由。全量测试 `166 passed`。

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
