# 运行环境隔离进度

> 源码边界更新：2026-08-21；真实运行证据截至 2026-08-07。

> 状态：隔离运行时主路径已实施；`qwen_tts`、`qwen_asr` 和 `fun_asr` 环境已按项目内 Python 重建，前两者已真实验收，Fun-ASR 缺模型资产。

## 原则

- 不在 APP 启动、浏览模型列表或刷新状态时创建环境、安装依赖或下载模型。
- 按已确认的依赖冲突划分环境，不为每个模型单独创建环境。
- 模型资产继续统一存放在 `models/`；虚拟环境只保存 Python 运行依赖。
- 默认兼容模型继续在主进程执行，只有冲突模型通过子进程运行。
- readiness 只检查任务实际选择的模型，并以对应 Python 解释器为准。

## TODO

- [x] 核对当前已选择本地 Provider 的 Python、Torch/CUDA、系统工具和模型资产要求；未安装 Provider 保持按需处理。
- [x] 将 `runtime_profile` 收敛为可执行环境 ID，定义 `main`、`qwen_asr`、`qwen_tts`、`fun_asr`。
- [x] 实现 `RuntimeProfileResolver`，统一解析 `.runtimes/<id>` 和 Python 解释器，不保存机器绝对路径。
- [x] 模型安装仅在用户选择安装时创建目标隔离环境；模型资产继续共用 `models/`。
- [x] 依赖安装和模型状态检查面向目标解释器，并缓存短期探测结果。
- [x] TTS Runtime Router 按 `qwen3 -> qwen_tts` 路由；默认 Provider 仍在主进程执行。
- [x] 实现短生命周期 TTS Worker，通过 JSON StageProfile 和文件路径交换请求、产物及结构化错误。
- [x] 验收 `Qwen3-ASR -> 翻译 -> Qwen3-TTS`，确认两个隔离环境可在同一任务中顺序执行并退出 Worker。
- [x] FunASR 使用已声明隔离环境；环境可导入但模型资产缺失，因此保持不可执行事实。
- [ ] 只有真实解析或加载证明冲突时，才为 Kokoro、VoxCPM2 增加新的环境档。
- [ ] 最后补充客户端环境状态展示；客户端不负责推断依赖关系，也不自动安装。

## 当前边界

- 不预创建未选择的隔离环境；当前存在 `qwen_tts`、`qwen_asr`、`fun_asr`。
- Qwen3-ASR 0.6B 已验收；1.7B 不因权重存在而视为已验收。
- 不引入常驻模型服务、容器或多节点调度。
- `qwen_tts` Worker 每次阶段执行后退出并释放显存，不建设常驻推理服务。

## 已验证基线（2026-08-07）

- 主 `.venv` 以及三个隔离运行时均使用项目内 UV Python 3.12.13，不依赖系统或其他项目解释器；四个环境均通过依赖一致性检查。
- RTX 4070 Ti SUPER 的 CUDA 探测和真实张量运算通过。
- Qwen3 CustomVoice 通过服务层和正式 `/api/v1/tts/synthesize` 三次生成有效 24 kHz WAV；Worker 退出后无残留 Qwen Python 进程。
- Qwen3-ASR 0.6B 通过直接推理与正式双 Worker Pipeline；Fun-ASR 只确认运行时可导入，因缺模型资产仍不可执行。
- 默认 `Demucs -> Faster-Whisper Base -> DeepSeek -> Edge TTS -> FFmpeg` 与 `Qwen3-ASR -> DeepSeek -> Qwen3 CustomVoice` 两条单文件 Pipeline 均在 `export` 阶段完成。
