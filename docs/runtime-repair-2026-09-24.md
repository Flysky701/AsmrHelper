# 2026-09-24 本地模型运行环境修复

## 原因与修正

- 本机 RTX 5070 可被 NVIDIA 驱动识别；主 `.venv` 为 CPU 版 PyTorch。VoxCPM2 原先在主环境运行，因而缺少包且无法使用 CUDA。
- VoxCPM2 改用 `.runtimes/voxcpm2` 隔离环境，模型文件仍在 `models/voxcpm2`；安装、状态探测与实际 TTS worker 使用同一环境。
- CUDA 引导沿用工作区已有的 GPU 架构检测修正，RTX 50 系列使用 cu128。该既有修正及其测试与此次修复有直接依赖，纳入本次版本；其他无关既有改动保留。
- VoxCPM2 使用匹配 PyTorch 2.10 的 TorchCodec 0.10 系列；Windows 禁用可选 torch.compile 优化，并传递实际设备参数。
- Fun-ASR 环境安装到 `.runtimes/fun_asr`；FSMN VAD 安装到 `models/funasr/fsmn-vad`，两个主模型未重新下载。
- 模型目录新增 `is_auxiliary` 标记。纯依赖资源不再单独显示；主模型展示配套资源状态并保留统一修复入口。具有独立字幕对齐功能的 Qwen ForcedAligner 不隐藏。
- 修正 Fun-ASR 时间戳单位：sentence_info 和 timestamp 数组使用毫秒，token start_time/end_time 使用秒，按音频长度约束输出。无精确 CTC 时间戳时保留 VAD 粗粒度句段。

## 已验证

- Fun-ASR Nano、多语言版以及 FSMN VAD 的状态为已安装且可执行。
- 两个主模型实际识别 5.616 秒样例成功，字幕时间范围 0.42–5.60 秒；VAD 的 3 秒样例检测成功。
- Fun-ASR 真实检查首先在 CPU 环境执行，不将其描述成 GPU 性能验证。
- 为避免重复下载 2.7 GiB CUDA 包，按原安装 RECORD 的 SHA-256 校验项目 Qwen 环境的 PyTorch/TorchAudio 2.10.0+cu128 文件，重打包为本地轮子并安装到两个新环境。原 Qwen 环境未修改；轮子位于忽略的 `.tmp/verified-cuda-wheels`，不提交。
- VoxCPM2 与 Fun-ASR 均识别 RTX 5070 Laptop GPU；CUDA 张量计算成功。Fun-ASR Nano 与 VAD 完成 GPU 真实短音频复验。
- VoxCPM 2.0.3 通过真实项目 TTS worker 路由合成短中文音频：48 kHz、0.96 秒、峰值 0.4632、数据有限且非静音。产物 `.tmp/voxcpm2-repair.wav` 不提交；此检查不代表对全部音色或克隆质量的验收。
- 普通 VoxCPM2 文本合成默认不加载无须使用的参考音频降噪模型；该可选设置仍保留，不隐式触发额外模型下载。
- 前端构建通过，模型/运行时/HTTP 定向测试 82 项通过，Fun 时间戳与应用服务修正后 67 项通过（组合有重叠）。最终工作区全量回归 **603 passed**；不等同于所有主模型的实际效果验收。

重启应用后再验证。模型权重与隔离 Python 依赖是不同资源，不需要手动把辅助模型移到 Python 环境中。

## 官方参考

- [FSMN VAD](https://huggingface.co/funasr/fsmn-vad)
- [VoxCPM 加载与设备参数](https://github.com/OpenBMB/VoxCPM/blob/main/src/voxcpm/core.py)
- [TorchCodec 兼容版本](https://github.com/meta-pytorch/torchcodec)
