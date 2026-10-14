# 开发与验证

## 2026-10-14 Fly-PC 接手

本次工作保留在 `codex/cloud-tts-extension-20261013`，工作树为 `E:\Projects\AsmrHelper-worktrees\cloud-tts-extension-20261013`。没有合并 master、推进版本或发布。帮助与云端 TTS 速查提交为 `f5f623b04e1d23c6b65401682a9475c2965c804d`；台本修复提交为 `47d6fd1129e8a8871bf957e20ef511c77b2ca6f5`。本节另随接手提交保存，最新提交以该分支 `git rev-parse HEAD` 和 `git ls-remote origin refs/heads/codex/cloud-tts-extension-20261013` 一致为准。

- 启动当前测试工作树：双击这里的 `RUNGUI.bat`；`RUNGUI.bat --build-staged` 离线增量构建备用预览，`RUNGUI.bat --check` 检查当前源码与回执。运行中的窗口保留；新版准备好后正常关闭旧窗口再打开入口，不强杀进程。
- 实测：完整 Python 套件 **1179 通过、1 跳过**；全部桌面 Node 测试 **85 通过**；相关 Ruff、TypeScript、Vite 和 Cargo 离线原生构建通过。Python 测试使用隔离数据/状态/临时目录及当前源码的 `PYTHONPATH`；临时离线 runner 阻断外部网络。启动环境回归也使用独立数据目录，不读写真实用户配置。禁用 pytest 缓存插件产生的 `cache_dir` 提醒不影响结果。
- 台本入口：**工具 → 字幕工坊 → 台本转字幕**。默认对应录音与原文台本，预览修订确认后匹配；核对报告可重开，编辑器可试听、改时间与手工插句。未匹配内容不估时插入。纯台本只整理 TXT；参考 SRT/VTT 必须为同录音、同语言原文。LLM 默认关闭，主动开启才发送文本。
- 仍待验收：短段真实录音、角色/动作/章节、漏读/重复/额外台词、源文件/录音变化后重确认、历史草稿重开和重试不覆盖。未用真实模型或云端 API 验证听感、识别质量与超长录音性能。
- 限制：当前复用 ASR 字幕片段时间，**不是逐字强制对齐**；本地保守匹配遇识别差异需人工核对。ASR 只使用已安装 Faster-Whisper 权重；时长读取不支持的录音格式先转 WAV。长行需分句，复杂长录音仍需分章/人工检查。新确认稿提交新任务，旧任务重试沿用其原配置。TTS 台本流水线、多角色与空间效果未加入本轮。
- 可恢复清理：旧 `desktop/src-tauri/target/release/asmr-helper-local.exe`、同名 `.build.json` 和 `.d` 已送系统回收站，均核对内容哈希和原位置；随后该输出槽可重建。任务临时目录 `C:\Users\Fly\Documents\Codex\2026-10-14\task-3\check-data\pytest-temp`（2768 个合成测试文件，约 128 MB）也已回收并核对恢复元数据。逐项原路径、回收位置与哈希留在任务目录 `cleanup-manifest.json`；回收站没有清空。模型、配置、素材、依赖及其他分支成果保留。

## 日常桌面入口

原生构建优先使用完整的项目内 Node、Cargo 和 LLVM MinGW；项目工具集不完整时使用 PATH 中已安装的 Node 和 Cargo，沿用本机 Rust 工具链及缓存。两种方式均锁定依赖并离线构建，不自动安装工具；使用 MSVC 工具链的 PC 需已有对应 Visual Studio C++ 构建工具。

双击 `RUNGUI.bat`（或桌面“ASMR Helper 主项目”快捷方式）打开主项目独立桌面窗口。`GUIRun.bat` 与 `run.bat` 无参数也指向这个窗口。
它使用主项目源码、`.venv`、已有模型和配置，不复制 Python、不安装依赖、不启动浏览器，也不制作安装包。
桌面壳为 `desktop/src-tauri/target/release/asmr-helper-local.exe`；独立随机端口及令牌连接本次后端，关闭窗口会结束本次后端及其子进程，不接管 8000 上的服务。

每次运行 `RUNGUI.bat` 都核对源码、构建配置和产物 SHA-256；源码变更或缺少有效回执时，使用项目已有工具和 Cargo 缓存离线增量构建。构建失败会明确报错，不启动旧版，也不自动下载。`RUNGUI.bat --check` 只显示当前指纹、产物回执和占用状态；`--build-only` 只构建，`--build` 强制构建后尝试打开。
此入口固定主项目工作区；需要切换安装版工作区时使用对应安装版入口。

产物被运行中的窗口占用时，构建自动选择另一空闲产物；两者均被占用则报错，保留现有窗口和任务。`RUNGUI.bat --build-staged` 优先选择备用壳，只构建不打开。构建成功后原子写入 `.build.json`，记录源码指纹、时间、可执行文件和前端资源哈希；启动器只在指纹及哈希均匹配的产物中选择最新版本。构建期间源码变化时不发布有效回执。已有窗口时只准备新版，需手动正常关闭后再双击入口；启动器文件锁和主项目实例锁防止重复启动。

## 可选浏览器开发入口

显式执行 `GUIRun.bat --vite`、`GUIRun.bat --dev` 或 `run.bat dev`。
默认只启动当前项目的 Python API（源码自动重载）与 Vite（React 热更新），打开浏览器；不会自动安装依赖、编译 exe 或生成安装包。
API 优先使用 8000；已有服务占用时为本次会话选择空闲端口，并把地址传给 Vite。Vite 固定使用 5173，被占用时退出，不接管其他前端。
启动日志显示源码、Python、Node 和实际 API 地址；只有当前会话身份核对通过后才打开前端。
按 Ctrl+C 或关闭启动控制台会结束本次启动的后端、重载子进程和 Vite，已有服务保留。

`GUIRun.bat --check` 只检查工具、API 基础依赖和端口；`GUIRun.bat --smoke` 启动并验证 HTTP 后自动退出。
日志在 `logs/dev`。需要固定 API 端口时执行 `.\.venv\Scripts\python.exe -B scripts/dev.py --port 18000`。
浏览器模式用于页面/API 热更新；原生对话框使用上面的日常桌面入口验证。
`--installed` 和 `--release` 保留为显式旧桌面操作，默认入口不会选择它们。

重写候选源码目前在 `.tmp/full-stack-v2` 的 Git worktree，存在未提交工作，禁止整体清理 `.tmp`。
`GUIRun.bat --rewrite` 用同一开发启动器打开重写源码，`GUIRun.bat --rewrite --smoke` 验证后退出。
该入口读取本机 `config/dev-runtime-sources.json`，只读借用已存在的 Python；模型来源仍由候选版自己的 `config/model_sources.json` 管理。
两个 Vite 会话共用 5173，先退出一个再启动另一个；它们不会接管或停止对方。
`D:\AsmrHelper-Test` 是试用部署目录，不是源码仓库；其借用的模型和 Python 环境必须在清理前核对。

## 模型与运行环境分别操作

资源页提供“安装/修复环境”“下载模型权重”和“引用已有目录”，分别请求 `POST /api/v1/models/{id}/runtime`、`POST /api/v1/models/{id}/download`、`POST /api/v1/models/sources`。
下载接口不接受 `install_dependencies`，也不执行推理验证；引用目录仅保存 `config/model_sources.json`，依赖缺失仍可保存引用。
可引用保留现有子目录结构的模型库、具名模型目录或 HF / Torch 缓存；页面分别显示权重、环境和实际位置。外部引用只读，“解除引用”不会删除外部文件。旧 `/install` 接口保留兼容，页面不再用它组合安装权重和依赖。

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
