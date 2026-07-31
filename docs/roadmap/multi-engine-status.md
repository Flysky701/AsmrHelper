# 多引擎支持现状

> 更新日期：2026-08-01
> 本页只记录当前代码、当前环境和真实验收状态。

## 当前结论

多引擎的注册、StageProfile、readiness、模型资源和 Workbench 选择链路已经恢复。
“已接线”不等于“已在当前机器验收”；没有安装依赖或模型的 Provider 会在任务创建前被 readiness 拦截。

| 类别 | Provider | 代码链路 | 当前环境 | 真实主链路验收 |
| --- | --- | --- | --- | --- |
| 分离 | `demucs` | 已接线 | 可执行 | 已通过 |
| ASR | `faster_whisper` | 已接线 | Base 可执行 | 已通过 |
| ASR | `fun_asr` | 已接线 | 未安装 | 待验收 |
| ASR | `qwen3_asr` | 已接线 | 未安装 | 待验收 |
| 翻译 | `deepseek` | 已接线 | 已配置 | 已通过 |
| 翻译 | `openai` | 已接线 | 未配置凭据 | 待验收 |
| TTS | `edge` | 已接线 | 可执行 | 已通过 |
| TTS | `qwen3` | 已接线并路由隔离 Worker | CustomVoice 可执行 | Server 真实合成通过；Pipeline 待验收 |
| TTS | `kokoro` | 已接线 | 缺 Python 包和 `espeak-ng` | 待验收 |
| TTS | `voxcpm2` | 已接线 | 未安装 | 待验收 |

默认真实验收组合仍是：

```text
demucs/htdemucs
→ faster-whisper/faster-whisper-base
→ deepseek/deepseek-chat
→ edge/default
→ ffmpeg
```

## 本轮恢复内容

- Fun-ASR、Qwen3-ASR 和 VoxCPM2 优先使用项目模型目录，不再绕过已下载资源重新解析上游名称。
- 只有单文本合成接口的 TTS Provider 可以通过通用时间线适配器进入 Pipeline；Kokoro 不再因缺少 `synthesize_segments` 被直接拒绝。
- Workbench 会提交明确的翻译模型和 TTS 默认模型。
- 模型依赖安装失败会在大模型下载前终止，异步任务会保留真实失败原因。
- “引擎与资源”可以触发 Faster-Whisper、Demucs、Kokoro 及其他可安装 Provider 的依赖安装。
- 下载脚本支持按 Provider 或模型 ID 选择，不再只认识 Whisper 和 Qwen3。
- 客户端异步安装已兼容纯 Python 包策略；Kokoro 不再误走模型权重下载分支。
- 客户端会提交模型默认安装模式，并为“资产已存在但 Python 依赖缺失”的模型提供修复入口。
- UV 依赖安装明确指向后端当前解释器；模型下载子进程会持续排空输出，避免长下载因管道写满卡住。
- 大模型安装在后端串行执行，避免多个 HuggingFace 权重并发争用带宽和当前 Python 环境；默认下载读取超时提高到 120 秒。
- 下载 subprocess 的真实异常会进入任务错误，不再统一折叠成“安装失败或依赖冲突”。
- 模型文件按目录声明精确校验，子目录中的同名权重不能再误判为顶层主模型已安装。
- HuggingFace snapshot 在单文件模式下下载；连接中断会自动重启下载进程并从 `.incomplete` 断点重试，最多三次。

## 安装与验收

优先在 APP 的“引擎与资源”页安装所选模型。命令行入口保留为排障和批量准备工具：

```powershell
.\.venv\Scripts\python.exe scripts\install_models.py --list
.\.venv\Scripts\python.exe scripts\install_models.py --provider fun_asr
.\setup.ps1 -Models -Engines fun_asr
```

Qwen3-TTS 与 Qwen3-ASR 当前锁定依赖存在冲突，不能把“安装全部引擎”作为同一 Python 环境的验收方式。选择其中一个安装档进行真实验收；在依赖关系更新前不绕过 UV 冲突约束。

2026-08-01 已为用户选择的 Qwen3-TTS 实施 `.runtimes/qwen_tts`：模型权重仍在共享 `models/`，主进程通过短生命周期 Worker 执行合成。Qwen3-ASR 只登记为独立 `qwen_asr` 环境 ID，未创建环境、未安装依赖。

后续按需隔离方案及实施边界见 [运行环境隔离 TODO](runtime-environment-isolation-todo.md)。该计划不阻塞当前模型下载链路修复，也不会在用户未选择安装模型时创建环境。

每个待验收 Provider 的最小完成条件只有三项：

1. readiness 通过；
2. 使用短音频或短文本完成一次真实推理；
3. 在 Pipeline 中确认产物和错误阶段正确。

不要求为每个 Provider 建立额外流程文档。
