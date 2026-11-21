# 文档

这里只维护当前行为和使用入口；过去的设计、排查过程与阶段验收通过 Git 历史查阅。

## 项目现状（2026-11-21）

新版创作台已在 `dev` 集成，源码版本为 `1.1.0`。工作台按 V2 节点图执行分离、识别、对齐、翻译、配音和混音。桌面端和 MCP 都可先审草稿、逐句重录，再生成双声道成品；批次可只重试失败项，重启后可复用有效节点产物。[开发分支](https://github.com/Flysky701/AsmrHelper/tree/dev) · [稳定主线](https://github.com/Flysky701/AsmrHelper/tree/master)

| 开发线 | 本次集成的范围 |
| --- | --- |
| 新版创作台 | `feat/ui-v2-redesign` 的 161 个工作树文件已在提交 `72ddbd3` 保存并合入 `dev`，包含创作台、审稿页、工作流编辑、算力设置和声学处理。 |
| 全栈重写 | `rewrite/full-stack-v2` 仍基于较早的 `8058445`，保留在独立工作树。11 月 21 日盘点时有 26 个已修改文件和 9 个未跟踪文件，涉及模型复用、运行环境及试用版更新。 |

`8351a32` 已通过 GitHub Windows CI：后端 1,124 项、前端 90 项全部通过，Ruff、TypeScript 和 Vite 构建通过。回归覆盖 V2 批次产物、节点恢复、连接快照、草稿审核与模拟 GPU Worker。真实作品听感、Colab 实机推理和新 Windows 安装包仍待验收。[本次 CI](https://github.com/Flysky701/AsmrHelper/actions/runs/44882744461)

GitHub Releases 在核对时标记的最新版是 10 月 12 日的 `v1.0.0`。远端还有 `v1.0.1` 标签，未查到对应的 Release 页面。[发行记录](https://github.com/Flysky701/AsmrHelper/releases)

## 安装与使用

- [中文快速上手：第一份配音](guides/quick-start.md)
- [安装、运行、数据与备份](guides/installation.md)
- [AI Agent 协作（MCP / Skill）与 Colab 云端算力指南](guides/agent-and-colab-guide.md)
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
- [模块化分层与 Agent 驱动演进契约（V2）](contracts/modular-agent-architecture.md)

工作台以 V2 图为执行依据。V1 历史可查询，具备完整绑定的旧工作流可迁移。HTTP 字段以 [Pydantic schema](../src/api/http/schemas/) 为准，运行实例可通过 `/docs` 或 `/openapi.json` 查看接口定义。模型资源以 [模型目录](../config/models.yaml) 为准，实际可运行性还取决于本机依赖和服务权限。

- [Windows 1.0.0 待验收与 beta 兼容](windows-release-1.0-acceptance.md)
