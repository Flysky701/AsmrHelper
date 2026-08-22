# AsmrHelper 最终验收矩阵（2026-08-07）

本文把本轮 Goal 的交付要求逐项映射到当前源码、自动测试、真实运行和 GUI 证据。能力状态定义以[后端能力事实清单](../../roadmap/backend-capability-baseline.md)为准；“代码存在”不单独计为可用。

## 1. 执行与数据契约

| 要求 | 当前结论 | 权威证据 |
| --- | --- | --- |
| Task / Dispatcher | 已完成 | 单一 Dispatcher/ExecutorRegistry 管理提交、排队、执行一次、取消和终态；未知或未绑定执行器会明确失败 |
| 状态、错误与重试 | 已完成 | TaskStatus 是事实源；错误保留 code/stage/detail；重试创建新 task 并保留 `retry_of_task_id` |
| Artifact 归属 | 已完成 | Pipeline、Tool、字幕和 Voice 产物按 task_id 登记；失败隔离与批量归属验收通过 |
| 持久化 | 已完成 | SQLite 保存终态 TaskSpec/TaskStatus/Artifact；重启删除未完成任务，历史终态只读 |
| 重复执行入口 | 已清理 | 已删除 Pipeline start/execute 和 Tool 同步 HTTP 重复入口；模型、Voice、字幕和 Tool 创建即提交 |

详细契约见 [Task Execution V1](../../contracts/task-execution-v1.md) 和 [Schemas V1](../../contracts/schemas-v1.md)。

## 2. 功能模块

| 模块 | 源码与契约 | 真实运行结论 |
| --- | --- | --- |
| 默认 Pipeline | StageProfile V1、readiness、阶段进度、取消、结果查询 | `Demucs → Faster-Whisper Base → DeepSeek → Edge TTS → FFmpeg` 完成，得到 5 个有效 Artifact |
| 可选双 Worker Pipeline | Qwen ASR/TTS 通过隔离 RuntimeRouter | `Qwen3-ASR 0.6B → DeepSeek → Qwen3 CustomVoice` 完成，得到混音、字幕、TTS 和 ASR 文本，无 Worker 残留 |
| ASR / 分离 / 翻译 / TTS / 混音 | 正式产品由 Pipeline 调用；直连接口只作 Provider 诊断 | 默认组合和关键 Qwen 组合均已覆盖实际推理 |
| 字幕 | 短操作同步；字幕翻译和台本转换为后台 Task | 字幕翻译 Tool 和纯文本台本任务完成，自动输出与 Artifact 正确 |
| 音频工具 | 分离、转换、切分、字幕翻译、音量预览统一 Tool Task | 五种工具连续真实 HTTP 验收完成；前四种登记独立 Artifact，音量预览返回分析结果 |
| Voice | Design/Clone/Preview 为后台 Task；Analyze 为同步结构化查询 | 四项正式 API 均完成真实验收；参考音频、prompt cache、试听 WAV 和分析结果有效 |
| 模型与运行时 | installed/executable/issues 分离；安装为统一后台 Task | main/qwen_tts/qwen_asr/fun_asr 环境使用项目 UV Python；Qwen ASR/TTS 与 Fun-ASR Nano 独立推理通过 |
| 批量与恢复 | 当前产品边界为多个独立 Task，不建设 BatchRun | `completed → failed(tts) → completed` 不互相阻塞；取消重提、Worker 异常清理和下载断点重试已验收 |

Fun-ASR Nano 当前已安装且可执行，但只完成独立运行时转写，尚未完成 Pipeline 级产物验收。VoxCPM2（未安装）和 OpenAI（未配置凭据）仍是可选 Provider 的真实不可用状态，不属于默认产品组合，也不以“已接线”冒充已验收。

## 3. 桌面 APP 与环境

- `setup.ps1` 使用项目级 UV cache/Python，主环境与隔离环境不继承其他项目 Conda。
- `verify_env.py` 已从项目外目录执行通过，当前注册 86 条 API 路由。
- `GUIRun.bat` 支持 installed/dev/release，隐藏启动后端、写入持久日志并清理真实 PID。
- Workbench、TaskCenter、SubtitleWorkshop、VoiceLab、AudioTools、EnginesResources 和 Settings 已按后端事实接线；未实现的 BatchRun 和未验收 Provider 不在 GUI 中伪装为可用。
- Tauri 原生对话框插件、`dialog:default` 权限和音频资产协议已配置；历史 release 已实机打开原生音频选择框，当前实现未改变该调用链。
- 最新 release 已真实启动并请求 capabilities、tasks、presets、voice profiles、Edge voices、模型状态和设置；窗口与后端均响应正常。
- 通过一次性本地 WebView2 CDP 对当前真实 Tauri 窗口逐页点击 7 个页面；任务历史、工具、字幕、Voice、设置以及 readiness 完成后的 17 个模型状态均正确呈现。
- 点击工作台“添加音频”后页面失焦、主窗口进入模态等待，确认当前 release 的原生文件选择框接管；历史实机已确认“音频”过滤器，插件权限和调用链未改变。
- TaskCenter 选择 `pipeline-2` 后读取到仍真实存在的主音频 Artifact；播放器显示 8 秒时长，点击后进度由 `0:00` 前进到 `0:02` 且按钮切换为暂停，结果查询、文件服务和播放链路通过。
- 主窗口关闭残留缺陷已修复；新 release 连续 3 次完成标准关闭、APP 退出和后端端口释放。

Codex Computer Use 在宿主目录初始化时被 `EPERM` 阻断，本轮使用 WebView2 CDP 完成了最新 Tauri 窗口内部页面点击，并用窗口焦点/模态状态确认原生对话框接管。由于自动化会话无法枚举交互桌面中的系统对话框内部文本，过滤器名称仍引用历史实机证据；后续若修改对话框插件、权限或过滤器配置，应重新进行人工可见检查。

## 4. 最终自动化基线

```text
pytest: 254 passed
API routes: 86
compileall: passed
Ruff F821/F601/F401: passed
UV lock check: passed (260 packages)
desktop production build: passed
Tauri release build: passed
Rust cargo fmt --check: passed
```

正式程序：`desktop/src-tauri/target/release/asmr-helper.exe`

## 5. 保留边界

- 保持单进程、低并发 Dispatcher，不引入 Redis/Celery 或分布式调度。
- 任务重启后不续跑；未完成任务清理，终态历史只读。
- 多文件 Workbench 等于多个独立 Task；只有明确需要批次级查询/取消时才设计 BatchRun。
- `.runtimes/*-backup-*` 是迁移安全备份，未经用户确认不删除；它们不参与当前运行。
