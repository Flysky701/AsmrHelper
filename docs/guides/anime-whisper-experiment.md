# Anime Whisper 可选 ASR 适配与验收

2026-11-12，基于 `experiment/anime-whisper-asr` 的
`5a8b5f3eb32d4a77bc2fc0224fab3eb9d41fe402`。
本功能保留 experimental 标记：接入与 CPU 推理已验收，识别质量和精细时间轴仍需评估。

## 使用

在“引擎与资源”中选择 Anime Whisper，使用已有的“安装/修复环境”和“下载模型权重”。
也可从仓库根目录运行现有安装入口：

```bash
uv run python scripts/install_models.py --model anime-whisper
```

Provider 为 `anime_whisper`，模型/资源 ID 为 `anime-whisper`，上游 ID 为
`litagin/anime-whisper`。默认 Faster-Whisper、预设和冻结参数不改变。

```python
from src.app.services.asr_engine_service import AsrEngineService

result = AsrEngineService().transcribe_file(
    input_path="sample-ja.wav",
    output_path="output/anime-whisper/sample-ja.srt",
    provider="anime_whisper",
    model="anime-whisper",
    provider_options={"device": "auto", "batch_size": 1},
)
print(result.text)
```

## 加载与依赖

- 模型：[litagin/anime-whisper](https://huggingface.co/litagin/anime-whisper)。实际下载的
  revision 为 `22e2008a8182b357da3922a6308d095008f72973`。
- 架构为 `WhisperForConditionalGeneration`，两层 decoder、HF safetensors 权重；
  不假定它直接兼容 CTranslate2/Faster-Whisper，本次未转换权重。
- extra 为 `anime_whisper`，PyTorch `>=2.4.0`、Transformers `>=4.57.3,<5.0.0`；
  复用已有 Transformers 4.57.x 锁定依赖，没有改变任何现存依赖的锁定条目。
- 复用 `.runtimes/anime_whisper`、现有 Worker、依赖准备及 CPU/CUDA 配置脚本。
  默认 batch size 为 1；`auto` 选择 CUDA/CPU，分别使用 FP16/FP32。
  基础依赖中的 NumPy 和 imageio-ffmpeg 负责单声道 16 kHz 解码，不要求 PATH 中的
  FFmpeg 或 Torchaudio 重采样；不使用 `device_map`，不额外引入 Accelerate。
- 资源目录声明 Windows、Linux；macOS 未列入本项目运行环境安装器的支持声明。
  本次实测平台仅 Linux CPU，Windows/CUDA 待实机验证。

## 通用模型功能

| 功能 | 验证范围 |
| --- | --- |
| 能力目录、模型列表、工作流选择 | 复用现有描述和通用界面；HTTP schema 已测，桌面界面代码已审阅 |
| 环境安装/修复 | 实际创建独立 CPU 环境，pipeline 导入、计算设备和资源就绪检查通过 |
| 下载、进度、完整性校验 | 现有 ModelService 实际完成 HF snapshot 下载、进度回调、所需文件校验和所有权登记 |
| 跳过已有权重、本地路径优先 | 针对本模型测试通过；真实推理在 HF 离线模式使用已下载目录 |
| 镜像源 | 通用下载器镜像参数传递已模拟验证；未访问真实镜像站 |
| 外部权重复用 | 针对本模型测试目录发现、复用和只读保护，不接管外部目录所有权 |
| 删除权重 | 针对本模型配置测试临时安装目录的所有权及删除；原有删除保护回归通过 |
| 下载与环境修复分离 | 下载不安装依赖、环境修复不下载权重，均有针对本模型的测试 |

没有新增另一套下载器、资源管理器或测试框架。

## 时间戳处理与评审修正

仅公开日语 `ja`、`device`、`batch_size`、`no_repeat_ngram_size` 和
`repetition_penalty`。作者提示 initial prompt 降低质量，因此不公开该参数，不传
`prompt_ids`，并关闭原生长音频生成中的前段 token 上下文。

请求原生分段时间戳，标记为 `whisper_segment`，不伪造置信度。上游词级
`alignment_heads` 引用了超出两层 decoder 的层号，因此不开放词级时间戳，
也未编造未经验证的对齐头。

真实实验暴露并修正了两个 mock 不足以发现的问题：

1. 最后字幕段可能有起点却没有终点。保留模型起点，仅将最后一段闭合到实测音频结尾，
   标记 `whisper_segment_audio_end`；此终点是音频边界，不是精确语音对齐。
   缺起点、中间缺终点、NaN、反向和完全越界区间仍报错，不均分文字时长。
2. Transformers 重叠分块拼接在 35 秒重复台词样本中漏掉第二次台词。最终改用
   Whisper 原生长音频路径，不设置 `chunk_length_s`，验证保留两次台词。

**时间戳精度未通过验收。** 上述长样本的两次台词仍合成一个较长字幕段。
当前适配保留文本和时间戳来源，不保证自动生成精细字幕分段；需要精细时间轴时，
可使用项目已有的独立对齐步骤，并试听检查边界。

## 回归验证

独立 master 基线 worktree 的同组原有测试 **244 passed**；最终适配后同组加上
新增测试共 **265 passed**（新增 **21 项**）。逐项比较确认原有能力描述、资源条目、
应用默认配置和现有依赖锁定条目不变。

```bash
python -m pytest -q tests/test_anime_whisper_backend.py tests/test_anime_whisper_resources.py tests/test_provider_model_onboarding.py tests/test_fun_asr_backend.py tests/test_fun_asr_timestamps.py tests/test_qwen3_asr_backend.py tests/test_asr_local_model_path.py tests/test_provider_parameter_calibration.py tests/test_model_catalog.py tests/test_model_resource_service.py tests/test_model_resource_actions.py tests/test_model_safe_removal.py tests/test_auxiliary_model_visibility.py tests/test_runtime_isolation.py tests/test_runtime_probe_cache.py tests/test_compute_install.py tests/test_configure_compute.py tests/test_http_api.py tests/test_qwen3_asr_http_api.py tests/test_fun_asr_http_api.py tests/test_app_services.py tests/test_cli.py
python -m ruff check src/core/engines/asr/anime_whisper.py tests/test_anime_whisper_backend.py tests/test_anime_whisper_resources.py
uv lock --check --offline
git diff --check
```

新增自动测试使用 mock 权重/推理；其中解码和 SRT 导出实际执行。下面的真实实验
单独执行，不计入 pytest 模拟测试数量。

## 已执行的真实 CPU 实验

使用公开[日语样本](https://huggingface.co/datasets/japanese-asr/ja_asr.reazonspeech_test/resolve/main/sample.flac)，
以及同一样本重复两次、中间插入 29 秒静音的跨 30 秒样本；不提交音频和权重。

环境：PyTorch **2.10.0+cpu**、Transformers **4.57.6**、Hugging Face Hub **0.36.2**，
4 个 OMP/MKL 线程，Linux，`HF_HUB_OFFLINE=1`。
两例均走 `AsrEngineService → RuntimeRouter → 独立 Worker → Adapter → SRT`，
写入字幕后重新解析验证时间范围。

| 样本 | 时长 | 单次端到端耗时 | 结果 |
| --- | --- | --- | --- |
| 日语短样本 | 3.111 秒 | 19.010 秒 | 返回文本和 SRT，末尾使用音频边界标记 |
| 两次台词 + 29 秒静音 | 35.221 秒 | 76.305 秒 | 保留两次台词、SRT 有效；仍合成一个较长字幕段 |

两例运行过程中子进程最大峰值 RSS 约 **3.54 GiB**，是 Linux 子进程统计，不是显存。
耗时包含进程启动和重新加载模型；单次 CPU 冒烟不能作为纯模型速度基准或性能保证。
没有人工参考文本，未计算 CER，也未比较 ASMR 数据质量。

尚待验证：Windows/CUDA、macOS、不同长度/编码的真实用户音频、精细字幕边界、
ASMR 识别质量及稳定性能。该模型仍是主动选择的实验引擎。
