# AsmrHelper 当前源码基线

日期：2026-09-10

## 当前事实与入口

清理基于 `master` 提交 `39d127e`。源码和现有行为测试优先于设计稿。
正式入口为 `GUIRun.bat` 启动的 Tauri 桌面端，后端为本机 FastAPI HTTP API。
`src/cli.py`、`scripts/asmr_bilingual.py` 和 `scripts/batch_process.py` 仍是实际使用的兼容入口。
Python 要求 `>=3.11,<3.13`；`setup.ps1` 管理 `.venv` 与 `.runtimes`。

| 目录 | 职责 |
| --- | --- |
| `src/api/http/` | HTTP 路由、请求与响应 schema |
| `src/app/services/` | 应用服务和任务提交 |
| `src/core/engines/` | ASR/LLM/TTS/Separator 注册与运行 |
| `src/core/orchestration/` | Pipeline 和 Tool 编排 |
| `src/core/tasks/`、`src/core/batches/` | 任务生命周期和批次聚合 |
| `src/core/artifacts/` | 产物索引与结果视图 |
| `src/core/resources/`、`src/core/runtime/` | 模型安装、readiness 与隔离运行时 |
| `src/core/subtitles/` | 字幕和台本处理 |
| `desktop/src/` | 页面、HTTP 封装、状态与音频播放器 |

`src/core/asr`、`src/core/tts`、`src/core/vocal_separator` 和 `src/mixer` 仍含真实实现，不能仅因目录名旧而删除。

## 当前接口约定

| 能力 | 入口 |
| --- | --- |
| Pipeline | POST `/api/v1/pipeline-runs`，202 |
| BatchRun | POST `/api/v1/batch-runs`，202 |
| 工具目录 | GET `/api/v1/tools` |
| 工具执行 | POST `/api/v1/tool-runs`，201，后台执行 |
| 台本任务 | POST `/api/v1/subtitles/script-to-subtitle/tasks`，201 |
| 模型安装 | POST `/api/v1/models/{id}/install`，默认创建任务 |
| Voice | `/api/v1/voice/*`，设计、克隆和试听返回后台任务 |
| 任务状态、结果、产物 | GET `/api/v1/tasks/{id}`、`/result`、`/artifacts` |
| 任务审阅与备注 | PATCH `/api/v1/tasks/{id}/review`、PUT `/review-note` |

接口迁移映射见 [兼容与迁移说明](../contracts/compatibility.md)。
能力目录使用 `GET /capabilities` 的 `category/provider` 查询参数；设置读取只使用 `GET /settings`。
台本 HTTP/schema 命名统一为 subtitle；已持久化的 `subtitle.script_to_vtt` TaskType 保留。
同步 Provider 诊断和字幕编辑仍有独立用途，不能因桌面当前没有直接调用就认定为死接口。

## 任务和运行时边界

- TaskStatus 是状态事实源；取消是协作请求，重试创建新 Task。
- 结果保持 `primary_artifact_id + artifacts + warnings`；产物归属 Task。
- SQLite 保存终态历史与产物，重启不恢复中断执行，历史任务只读。
- BatchRun 聚合普通 Pipeline Task，不引入第二套执行器。
- ASR：Faster-Whisper、Fun-ASR、Qwen3-ASR；TTS：Edge、Qwen3、VoxCPM2；LLM：DeepSeek、OpenAI；Separator：Demucs。
- 模型已安装、依赖可导入、readiness 通过与真实推理验收是不同状态。
- 历史真实验收范围见 [多引擎支持现状](multi-engine-status.md)，本轮没有重新执行模型推理或 Windows 桌面验收。

## 本轮精简

- 删除历史归档、2026-05 UI 重设计蓝图及配套 sketch；历史由 Git 保存。
- 删除旧入口不存在、源码字符串和导入位置之类的迁移测试，保留模型卸载与工具派发行为测试。
- 删除无调用的音频、ASR、音色、缓存与服务辅助方法，以及配置转发包和未使用 schema。
- 删除重复路由、无调用前端 API 方法和重复模型 SSE 客户端；任务事件仍由 `tasksApi` 订阅。
- 移除未接入开发流程的 Black 依赖和配置，保留 Ruff；保留实际使用的 Python、前端和 Rust 依赖。
- 显式声明已直接使用的 Pydantic 和 SciPy，避免 API schema 与基础音频转换依赖可选包的传递安装；同步 `uv.lock`。
- 不增加模块、测试用例或兼容转发层。

## 验证

- 现有测试：`324 passed`；删除 21 个迁移/旧路由负向测试项，无新增用例。
- 前端：`tsc -b && vite build` 通过。
- Python：`compileall` 和 Ruff `F401/F811/F821/F601` 检查通过。
- `uv lock --check`、`git diff --check` 和当前 Markdown 相对文件链接检查通过。
- Linux 验证环境额外安装 CPU Torch 与 Faster-Whisper 以执行现有测试；未下载模型权重或进行真实推理。
- 测试依赖出现一条 Starlette/AnyIO 弃用提示，不影响上述通过结果。

## 维护原则

只保留服务当前功能的代码、文档和测试。删除前检查实际入口、动态注册、脚本和外部 HTTP 语义；未使用的未来扩展不保留。
接口变更同步调用方、现有相关测试与契约。完成的计划和旧快照由 Git 追溯，不再积累归档目录。
