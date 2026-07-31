# 运行环境隔离进度

> 状态：第一阶段已实施；`qwen_tts` 已落地，`qwen_asr` 仅完成环境 ID 声明，尚未创建环境或验收。

## 原则

- 不在 APP 启动、浏览模型列表或刷新状态时创建环境、安装依赖或下载模型。
- 按已确认的依赖冲突划分环境，不为每个模型单独创建环境。
- 模型资产继续统一存放在 `models/`；虚拟环境只保存 Python 运行依赖。
- 默认兼容模型继续在主进程执行，只有冲突模型通过子进程运行。
- readiness 只检查任务实际选择的模型，并以对应 Python 解释器为准。

## TODO

- [ ] 逐个核对本地 Provider 的 Python、Torch/CUDA、系统工具和模型资产要求；Qwen3-TTS / Qwen3-ASR 冲突已确认，其余按实际选择继续。
- [x] 将 `runtime_profile` 收敛为可执行环境 ID，首批定义 `main`、`qwen_asr`、`qwen_tts`。
- [x] 实现 `RuntimeProfileResolver`，统一解析 `.runtimes/<id>` 和 Python 解释器，不保存机器绝对路径。
- [x] 模型安装仅在用户选择安装时创建目标隔离环境；模型资产继续共用 `models/`。
- [x] 依赖安装和模型状态检查面向目标解释器，并缓存短期探测结果。
- [x] TTS Runtime Router 按 `qwen3 -> qwen_tts` 路由；默认 Provider 仍在主进程执行。
- [x] 实现短生命周期 TTS Worker，通过 JSON StageProfile 和文件路径交换请求、产物及结构化错误。
- [ ] 先验收 `Qwen3-ASR -> 翻译 -> Qwen3-TTS`，确认两个冲突环境可在同一任务中顺序执行并释放显存。
- [ ] 只有真实解析或加载证明冲突时，才为 FunASR、Kokoro、VoxCPM2 增加新的环境档。
- [ ] 最后补充客户端环境状态展示；客户端不负责推断依赖关系，也不自动安装。

## 当前边界

- 不预创建未选择的隔离环境；当前只存在 `qwen_tts`。
- 不安装 Qwen3-ASR 依赖或模型。
- 不引入常驻模型服务、容器或多节点调度。
- `qwen_tts` Worker 每次阶段执行后退出并释放显存，不建设常驻推理服务。

## 已验证基线（2026-08-01）

- 主 `.venv` 保持 Torch CPU 与 `transformers 4.57.6`；Qwen3-TTS 环境使用 Torch `2.10.0+cu126`、`transformers 4.57.3` 和 NumPy `2.4.6`。
- RTX 4070 Ti SUPER 的 CUDA 探测和真实张量运算通过。
- Qwen3 CustomVoice 通过服务层和正式 `/api/v1/tts/synthesize` 三次生成有效 24 kHz WAV；Worker 退出后无残留 Qwen Python 进程。
- Pipeline 真实任务由用户下一步手动验收。
