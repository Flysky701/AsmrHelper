# 文档

这里只维护当前行为和使用入口；过去的设计、排查过程与阶段验收通过 Git 历史查阅。

## 安装与使用

- [安装、运行、数据与备份](guides/installation.md)
- [工作台](guides/workbench.md)
- [节点流水线与图契约](guides/workflow-graph-v2.md)
- [声音库、音色规则与试听](guides/voice-lab-v2.md)
- [TTS 能力、连接与执行](guides/tts.md)
- [声音库识别与手动选段](guides/reference-selection.md)
- [声音库会话与页面切换](guides/reference-session-lifecycle.md)
- [音色描述词](guides/voice-description.md)

## 开发与接口

- [开发、目录职责与验证](guides/development.md)
- [分支与发布](guides/branch-workflow.md)
- [Pipeline 提交契约](contracts/mainline-v1.md)
- [请求、任务、产物与事件字段](contracts/schemas-v1.md)
- [任务执行、重试与恢复](contracts/task-execution-v1.md)
- [Provider、设置与就绪检查](contracts/provider-v1.md)
- [Provider / Model 接入](contracts/provider-model-onboarding.md)
- [现有格式的兼容边界](contracts/compatibility.md)

工作台以 V2 图为执行依据；V1 请求及历史数据的兼容并不代表桌面仍使用固定全流程。HTTP 字段以 [Pydantic schema](../src/api/http/schemas/) 为准，运行实例可通过 `/docs` 或 `/openapi.json` 查看接口定义。模型资源以 [模型目录](../config/models.yaml) 为准，实际可运行性还取决于本机依赖和服务权限。
