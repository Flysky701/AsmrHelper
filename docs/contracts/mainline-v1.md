# 主链路契约 v1

> 状态：目标契约  
> 适用范围：桌面端、后端 API、Pipeline 编排器  
> 实现差异：见 [兼容与迁移说明](compatibility.md)

## 1. 目标

桌面端只负责提交、观察和控制任务，不参与后端内部编排。一次主链路请求应完成输入登记、执行配置绑定、任务创建和排队，并立即返回可查询的任务。

主链路固定为：

`输入 → 分离 → ASR → 翻译 → TTS → 混音 → 导出`

当前不支持用户自定义 DAG。阶段可按配置跳过，但顺序和阶段标识保持稳定。

## 2. 桌面端主链路

1. 桌面端提交 `POST /api/v1/pipeline-runs`。
2. 后端完成轻量参数校验，创建任务并返回 `202 Accepted`。
3. 桌面端通过 `GET /api/v1/tasks/{task_id}` 获取事实状态。
4. 任务完成后，通过 `GET /api/v1/tasks/{task_id}/result` 获取产物。
5. 取消、重试均以任务为操作对象。

桌面端不得依赖后端进程标准输出判断任务状态，也不得自行拼接内部工具命令。

## 3. 权威 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/pipeline-runs` | 创建并排队一个主链路任务 |
| `GET` | `/api/v1/tasks/{task_id}` | 查询任务及各阶段状态 |
| `GET` | `/api/v1/tasks/{task_id}/result` | 获取最终结果和产物索引 |
| `POST` | `/api/v1/tasks/{task_id}/cancel` | 请求取消任务 |
| `POST` | `/api/v1/tasks/{task_id}/retry` | 基于原始请求创建重试任务 |
| `GET` | `/api/v1/tasks/{task_id}/artifacts` | 查询任务产物 |

`/workspaces`、`/inputs`、`/sessions` 和通用 `/tasks` 属于高级或内部能力。它们可以保留，但不得要求 Workbench 为完成一次默认任务逐级编排这些资源。

## 4. 创建请求

```json
{
  "input": {
    "path": "E:/media/source.mp4",
    "companion_paths": []
  },
  "output": {
    "directory": "E:/media/output"
  },
  "execution_profile": {
    "version": 1,
    "source_lang": "ja",
    "target_lang": "zh",
    "stages": {}
  }
}
```

字段定义以 [数据结构契约](schemas-v1.md) 为准。

创建接口只做可快速完成的校验。模型加载、Provider 连通性和媒体探测等耗时检查由任务的 `prepare` 阶段完成，并通过标准任务错误返回。

## 5. 创建响应

成功时返回：

```json
{
  "task": {
    "task_id": "task_01",
    "task_type": "pipeline",
    "state": "pending",
    "stage": "prepare",
    "progress": 0,
    "message": "Task queued",
    "error": null,
    "created_at": "2026-07-23T10:00:00Z",
    "started_at": null,
    "finished_at": null
  }
}
```

HTTP 状态码为 `202`。业务任务执行失败不通过创建请求长时间阻塞后再返回，而是记录为任务状态。

## 6. 阶段语义

| 阶段 | 责任 | 典型产物 |
| --- | --- | --- |
| `prepare` | 输入探测、配置解析、运行前检查 | 输入元数据 |
| `separate` | 人声与伴奏分离 | vocal、accompaniment |
| `asr` | 语音识别 | 原文字幕 |
| `translate` | 字幕翻译 | 译文字幕 |
| `tts` | 语音合成 | 合成语音 |
| `mix` | 音轨混合 | 混合音频 |
| `export` | 封装与输出 | 最终视频或音频 |

每个阶段必须产生明确的 `pending`、`running`、`completed`、`failed`、`cancelled` 或 `skipped` 状态。失败时必须注明真实失败阶段，不得统一折叠为“分离失败”或其他前置阶段。

## 7. 队列与并发

- 创建任务必须快速返回，不得在请求线程内执行完整 Pipeline。
- 同一时刻只有一个任务时，不得因队列状态同步错误长期停留在 `pending`。
- 后端是任务状态的唯一事实源；桌面端只展示，不推断状态。
- 取消是请求语义。后端确认停止后，任务才进入 `cancelled`。
- 重试创建新任务，并通过实现内部关联保留来源；不得覆盖原任务事实。
- 终态任务（`completed`、`failed`、`cancelled`、`skipped`）及其产物索引持久化为历史记录。
- APP 重启时删除 `pending`、`running` 等未完成任务及其临时产物索引，不恢复中断的执行。
- 重启后历史任务只用于查看。由于输入会话和运行时资源不恢复，用户需要从 Workbench 重新提交输入文件。
- 持久化历史不等同于持久化执行队列。当前低并发场景保留进程内线程，不建设独立调度器；未来只有在真实并发需求出现后才重新设计。

## 8. 验收条件

- 默认参数能够提交任务并立即获得 `task_id`。
- 每个失败均能定位到阶段、错误代码和可读消息。
- 任务完成后，结果接口能返回一个明确的主产物。
- 前端无需读取后端日志即可区分排队、执行、失败、完成和取消。
- Provider 私有参数不会泄漏为跨层必填字段。
## 9. Task V1 execution boundary

The mainline and other long-running capabilities execute through the existing `TaskDispatcher`. `ExecutorRegistry` is the submission allow-list and concrete handler binding: unknown task types are rejected, and a missing callable becomes an explicit failure at dispatch.

Terminal states `completed`, `failed`, `cancelled`, and `skipped` do not accept lifecycle updates. Cancellation is a request; the dispatcher writes final `cancelled` only after the executor exits. Retry creates a new task with `retry_of_task_id`, and every artifact remains owned by the task that produced it.

See [Task Execution V1](task-execution-v1.md).
