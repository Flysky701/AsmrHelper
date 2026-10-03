# 开发与验证

## 代码入口

| 目录 / 入口 | 职责 |
| --- | --- |
| `desktop/src/pages`、`components`、`stores` | React 页面、交互与本次草稿；通过 HTTP 获取任务事实 |
| `src/api/http` | FastAPI 路由、Pydantic 请求与响应；`python -m src.api.http` 启动 |
| `src/app/services` | 校验、配置解析、任务提交及领域服务组合 |
| `src/core/orchestration/pipeline` | V1 阶段兼容和 V2 图规划、执行、产物与恢复边界 |
| `src/core/tasks`、`src/core/batches`、`src/app/persistence` | 统一执行器、任务状态、批次汇总与 SQLite 历史 |
| `src/core/speech` | TTS 能力、规则快照、编译和 Provider 执行 |
| `src/core/engines`、`runtime`、`resources` | 引擎适配、隔离 Worker、资源目录和运行环境 |
| `src/core/subtitles`、`src/mixer` | 字幕领域操作、时间轴和混音 |
| `src/cli.py`、`scripts/` | CLI、安装、启动和专项工具；不作为桌面另一套执行真相 |

桌面工作台使用 V2 图，任务与产物仍沿同一个 Dispatcher。不要让前端重新编排后台命令，或把 V1 兼容字段变成 V2 的隐藏执行开关。[提交契约](../contracts/mainline-v1.md)、[任务契约](../contracts/task-execution-v1.md)与 [TTS 指南](tts.md)说明边界。

## 安装和检查

先按 [安装指南](installation.md)准备环境。基础 setup 已包含开发工具；已有环境也可显式使用 `setup.ps1 -DevOnly`。依赖版本来自 `uv.lock` 和 `desktop/package-lock.json`，不以升级依赖代替修复。

从根目录运行 Python 检查：

```powershell
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m pytest
```

从 `desktop` 运行前端检查：

```powershell
node --test --test-isolation=none tests/*.test.mjs
npm.cmd run build
```

`npm run build` 执行 TypeScript 检查和 Vite 构建。按改动先运行相关测试，必要时运行聚合套件；一次性 mock、截图与探测输出留在仓库外，不作为生产代码或新的永久测试框架提交。

保留有价值的行为回归：图依赖与素材校验、只执行选中节点、翻译和声音连接快照、任务状态及异步归属、取消/重试/恢复、配置兼容和错误路径。避免只检查文件名、源码字符串或旧架构形状；旧测试失败应先核对它是否仍代表产品契约。不能为了通过测试删除仍有效的行为保护。

测试使用独立临时数据库、配置和输出。不要让 mock 访问真实凭据、启动模型或产生付费请求。mock 验证与真实模型、原生文件对话框和听感验收分别记录。

## 构建与本地运行

```powershell
# 项目根目录
.\GUIRun.bat --dev

# desktop 目录：构建 exe，不启动应用，不生成安装包
npm.cmd run tauri -- build --no-bundle
```

Tauri 构建先执行 `npm run build`。验证构建应使用隔离工作树或独立输出，避免覆盖用户正在使用的 release。正式更新前确认源码、当前任务与草稿，按 [安装指南](installation.md#启动和更新)正常关闭再更新。

模型资源和安装要求维护在 `config/models.yaml`；新 Provider 复用[接入说明](../contracts/provider-model-onboarding.md)。版本、分支和发布过程见[分支与发布](branch-workflow.md)。
