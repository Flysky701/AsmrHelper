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

- 只支持当前 V1 客户端；`/pipeline/run`、`/pipeline/tasks`、`/pipeline-runs/start`、`/pipeline-runs/execute`、旧同步工具执行和旧 `/tools/*` 动作接口已删除。
- `POST /pipeline-runs` 不再接受平铺 Pipeline 参数，只接受 `input/output/execution_profile`。
- 公共结果固定为 TaskResult；HTTP 响应不得出现 `files/primary_output`。
- 内部旧 DTO 或解析分支不得成为新能力入口，并应继续逐步移除。

### 2.1 当前保留边界与删除条件

| 兼容项 | 当前真实用途 | 删除条件 |
| --- | --- | --- |
| Python core 旧入口 | `src.core.model_manager` 与 `src.core.translate` 已删除；翻译、字幕和模型服务分别由各领域 registry 提供 | 已完成；历史负向架构测试已删除 |
| 路径型 `primary_output/files` | 仅存在于内部执行器模型 | 内部执行器全面改用 ArtifactRecord 后删除 |

## 3. 回归基线

至少覆盖：

- 默认参数启动一条完整任务；
- 缺少 Python 依赖时定位到实际阶段和依赖名；
- TTS 未返回音频时报告 `tts / PROVIDER_RESPONSE_INVALID`；
- 单任务不会永久停留在队列；
- 取消与重试不会覆盖原任务；
- 重启后终态历史和产物索引存在，未完成任务不存在；
- 设置保存后可读取脱敏状态，并能执行 Provider 实测；
- 最终结果存在一个明确主产物。

## 4. 接口精简（2026-09-10）

项目仅维护同仓桌面端和当前 V1 客户端；本轮直接迁移调用方，不增加兼容转发。

| 原入口 | 当前入口 |
| --- | --- |
| POST `/tasks/{id}/review-status` | PATCH `/tasks/{id}/review` |
| POST `/tasks/{id}/review-note` | PUT `/tasks/{id}/review-note` |
| GET `/task-queue` | GET `/tasks/queue` |
| GET `/settings/effective` | GET `/settings` |
| GET `/capabilities/{category}` | GET `/capabilities?category=...` |
| GET `/pipeline-runs/{id}`、`/tool-runs/{id}`、`/artifacts/by-task/{id}/result` | GET `/tasks/{id}/result` |
| 上述 Pipeline/Tool 的 `/artifacts`、`/artifacts/by-task/{id}` | GET `/tasks/{id}/artifacts` |
| POST `/pipeline/batch` | POST `/batch-runs`，使用现有 BatchRun 请求结构 |
| GET `/tool-runs` | GET `/tools`（工具目录） |
| POST `/tool-runs/tasks` | POST `/tool-runs`（创建并提交任务，201） |
| POST `/subtitles/script-to-vtt` | POST `/subtitles/script-to-subtitle` |
| POST `/subtitles/script-to-vtt/tasks` | POST `/subtitles/script-to-subtitle/tasks` |

结果字段保持 `task_id / primary_artifact_id / artifacts / warnings`。`ArtifactResponse` 和 `TaskResultResponse` 是规范 schema 名称；批量任务条目复用 `TaskCreateRequest`。
台本请求与响应统一为 `ScriptToSubtitleRequest/Response`，因为输出支持 VTT、SRT 和 LRC。
内部已持久化的任务类型 `subtitle.script_to_vtt` 保留，避免改动已有任务历史。

ASR/TTS/LLM 的同步诊断、字幕同步编辑、模型状态与能力目录的职责不同，保留各自入口。
CLI 的批量执行仍使用原应用服务；本轮只删除无人调用的同步批量 HTTP 入口。
历史设计和旧验收材料通过 Git 历史追溯，不在工作树保留归档副本。
