# VoxCPM 与 IndexTTS 耳语探索补充

## 资源修复后复测：成功

用户确认资源修复后，重新执行原脚本，进程退出码为 0。现有 VoxCPM2Engine 成功在 CUDA / BF16 下加载本地模型，无联网下载、无引擎或依赖修改。首次加载耗时 29.56 秒。

| 样本 | 音频时长 | 合成耗时（不含加载） | 峰值 CUDA allocated |
| --- | ---: | ---: | ---: |
| 普通 | 6.88 秒 | 12.39 秒 | 5.32 GiB |
| 耳语 | 8.48 秒 | 11.33 秒 | 5.37 GiB |

文件位于 `output/voxcpm-whisper-exploration/normal.wav`、`whisper.wav`，指标见同目录 `results.json`。两组都是 48 kHz 单声道，样本非空、非静音、数值有限，峰值分别为 0.339 和 0.381，未超过 1。耳语 RMS 为 0.0594，高于普通组的 0.0464，不能用音量大小证明或否定耳语效果。

本轮验证了真实合成成功；没有主观听评、真人参考克隆、完整视频配音或 IndexTTS 实测。两组采用无参考音频的 Voice Design，声线不保证一致。下文缺少 NumPy 的失败记录仅描述修复前状态。

日期：2026-09-24。用户反馈 Qwen3 耳语听感不理想；master 正在修 VoxCPM，因此本次仅新增独立试音脚本，不改引擎、运行时或依赖。

## VoxCPM 简单试跑

命令：`.runtimes/voxcpm2/Scripts/python.exe -u scripts/probe_voxcpm_whisper.py`。

结果：在导入阶段报 `ModuleNotFoundError: No module named 'numpy'`；检查发现该隔离环境 site-packages 当前只有虚拟环境引导文件。模型目录 `models/voxcpm2` 有配置和权重文件，但本次没有加载模型，也没有生成试听音频。这是环境未就绪，不能据此评价模型效果。

待既有修复完成，可重新执行上述命令。脚本使用离线本地模型、现有 VoxCPM2Engine、关闭降噪器，分别生成普通女声和耳语女声；输出位于 `output/voxcpm-whisper-exploration`。它是无参考音频的 Voice Design 初筛，两组不保证声线一致，不代表真人耳语克隆验收。重复执行覆盖同名结果。

## IndexTTS 的适用性

核查官方仓库时当前发布为 IndexTTS-2.5，支持中文、英文、日文、西班牙文和阿拉伯文。官方接口提供音色参考 `spk_audio_prompt`、独立情感参考 `emo_audio_prompt` 和强度 `emo_alpha`；2.5 还有 `duration_factor`（0.5–2.0，数值越大越慢），适合后续配音时长调整，但不能等同于精确时间轴对齐。

关键限制：文字情感描述会转换成情绪向量；文档列出的八维情绪包括开心、生气、悲伤、害怕、厌恶、低落、惊讶、平静，没有专门的耳语维度。因此“平静”或在 emo_text 填“耳语”不保证产生气声。这不是证明模型做不到耳语，而是现有文档不足以证明。

建议实验顺序：同一段可使用的真人耳语作为音色参考，先测试克隆；再比较增加独立耳语情感参考的效果，调整 emo_alpha。检查吐字、气声、呼吸、声线稳定性和漏字。不能只凭通用 WER/音色相似度指标判定 ASMR 质量。

本地接入可走现有独立 Runtime + TTS Provider 架构。应新建独立环境，避免与 VoxCPM/Qwen 依赖共装。Windows 初次测试可关闭 DeepSpeed、自定义 CUDA kernel 和 compile，使用 BF16；2.5 代码对不足 10 GB GPU 有长文本分块路径，但这不保证本机 8 GB 显存一定足够。参考音频控制可以先不加载 QwenEmotion。此次仅审查官方文档与源码，没有安装或实际听评 IndexTTS。

来源：

- https://github.com/index-tts/index-tts
- https://github.com/index-tts/index-tts/blob/main/indextts/infer_v2_5.py
- https://huggingface.co/IndexTeam/IndexTTS-2.5

结论：IndexTTS 值得作为参考音频驱动的第二候选；尚无本项目实测证据证明其耳语效果优于 VoxCPM 或 Qwen3。
