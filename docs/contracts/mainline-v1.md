# Pipeline 提交契约

桌面端负责选择、提交、观察和控制；执行内容由后端冻结的配置决定。当前工作台使用 V2 节点图，V1 阶段请求继续兼容。文档文件名保留以维持链接，不表示只接受 V1。

## 提交与查询

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/pipeline-runs` | 校验并提交一个 Pipeline，返回 202 与 `{task: ...}` |
| POST | `/api/v1/batch-runs` | 提交明确分组的批次，每组仍由普通 Pipeline Task 执行 |
| GET | `/api/v1/tasks/{id}` | 查询状态、阶段、进度与结构化错误 |
| GET | `/api/v1/tasks/{id}/spec` | 查询该任务的公开执行配置 |
| GET | `/api/v1/tasks/{id}/result` | 查询结果和产物索引 |
| GET | `/api/v1/tasks/{id}/artifacts` | 查询任务产物 |
| POST | `/api/v1/tasks/{id}/cancel` | 请求协作取消 |
| POST | `/api/v1/tasks/{id}/retry` | 按可用条件创建新任务，不覆盖原任务 |
| POST | `/api/v1/tasks/{id}/resume` | 仅对符合条件的 V1 检查点任务显式恢复 |

创建前校验结构、素材与所用资源，执行在共享 TaskDispatcher 中继续。桌面不能用 stdout 或旧错误卡代替任务状态；详情、迟到响应和产物须匹配所选任务 ID。选择流程或浏览历史不自动提交。

## 请求版本

单任务外层为 `input`、可选 `output` 和 `execution_profile`。`input.path` 仍是必填入口路径；V2 的各输入端口由 `execution_profile.bindings` 决定，不能仅凭入口路径推测所有素材。

- **V2**：`{version: 2, graph, bindings}`。图包含节点、连线、素材槽和明确交付结果，不接收另一份全局阶段开关。只检查和执行图中的节点；无效依赖、语言、时间轴、循环或歧义均报错，不补跑全流程。
- **V1**：`{version: 1, source_lang, target_lang, skip_existing, stages, workflow?}`。旧客户端未给版本且没有 graph 时按 V1 处理；保留已有阶段计划、显式 workflow 与恢复行为，不重新解释为 V2。
- **V2 批次**：使用共同的 `{version: 2, graph}` 和 `groups: [{group_id, label, bindings}]`。不混用 V1 `inputs`；所有组先通过校验，才创建批次。

完整字段见[数据结构](schemas-v1.md)与[节点图契约](../guides/workflow-graph-v2.md)。模型、路径、连接和字幕是否可执行仍需后端校验，结构合法不表示真实合成成功。

## 状态与结果

后端是事实源。任务状态为 pending、running、completed、failed、cancelled 或 skipped，进度范围为 0–1。V2 的执行阶段使用 node ID；生命周期准备阶段可以是 prepare。同类节点是不同实例，不能按能力名称覆盖产物。

公共结果使用 `task_id / primary_artifact_id / artifacts / warnings`。V2 最终交付由图的 outputs 与产物的 node_id/port 对应，未勾选交付的中间产物仍保留给下游。失败、取消或跳过不能伪装成所有节点完成。

重试创建新任务；批次由自身控制入口管理，不能通过单任务重试绕开分组归属。V2 不支持部分续跑、自动重跑或节点缓存；允许的显式重试从头执行该组图。V1 的检查点、远端结果未知保护与任务历史持久化见[任务执行契约](task-execution-v1.md)。
