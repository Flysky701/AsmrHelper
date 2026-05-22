# 模型资产管理需求草案 V1

## 目标

- 为后续持续接入新的本地模型建立统一的资产管理规则，而不是按单模型硬编码下载逻辑。
- 将“模型可见”提升为“模型可直接使用”。
- 让用户在桌面端点击下载后，无需额外执行命令、补依赖、补附属文件或手工排查环境，即可直接在任务流和工具页使用模型。

## 直接结论

当前仓库已经具备“按模型条目下载权重”的基础能力，但还不具备“点下载即可用”的完整能力。

现状主要限制如下：

- 模型安装是单 `model_id` 粒度，不支持“推荐组合下载”或“同类全部下载”。
- 模型元数据只覆盖权重目录和必需文件，不覆盖 Python 依赖、附属资产、平台约束和安装后校验。
- `Fun-ASR`、`Qwen3-ASR` 仍然依赖手工安装 optional extra。
- 当前没有显式的“模型家族”概念，也没有“共享依赖”和“冲突版本”的表达能力。

相关代码位置：

- [config/models.yaml](D:/WorkSpace/AsmrHelper/config/models.yaml)
- [src/core/resources/model_catalog.py](D:/WorkSpace/AsmrHelper/src/core/resources/model_catalog.py)
- [src/core/resources/model_installer.py](D:/WorkSpace/AsmrHelper/src/core/resources/model_installer.py)
- [src/api/http/routes/models.py](D:/WorkSpace/AsmrHelper/src/api/http/routes/models.py)
- [desktop/src/pages/EnginesResources.tsx](D:/WorkSpace/AsmrHelper/desktop/src/pages/EnginesResources.tsx)

## V1 范围冻结

为避免模型资产管理在第一轮就被多格式、多后端和社区衍生版本拖得过重，V1 先明确冻结以下边界：

- 本地统一支持仅覆盖 `PyTorch` 主线。
- 本地统一支持的具体形态包括：
  - `Transformers` 主线
  - 官方 Python package 主线
  - 官方或接近官方的附属资产下载方式
- 本地统一支持暂不覆盖：
  - `ONNX`
  - `GGUF`
  - `MLX`
  - `CoreML`
  - 社区转换版权重
- 非 `PyTorch` 主线格式如果后续要支持：
  - 优先作为云端能力补齐
  - 或作为单独扩展能力处理
  - 不纳入当前本地模型资产管理主框架

这意味着 V1 的目标不是“支持所有可运行格式”，而是“在主线 PyTorch 生态下，把下载后直接可用这件事做扎实”。

## 设计目标

### 1. 面向未来扩展

- 新模型接入应尽量通过元数据声明完成。
- 新增模型时，允许只补：
  - provider adapter
  - 模型元数据
  - 必要的安装后校验逻辑
- 不应每新增一个模型，就重写一套安装、状态判断和前端交互流程。

### 2. 用户零注意力安装

“点击下载即可直接使用”在本系统中的定义应为：

- 系统自动安装该模型运行所需的全部必需资产。
- 系统自动安装该模型运行所需的全部必需 Python 依赖。
- 系统自动安装或提示纳入“推荐组合”的附属资产。
- 系统自动做安装后校验。
- 只有通过校验后，模型状态才会显示为可用。

### 3. 区分通用规则与家族特化

不同模型家族会共享一部分通用安装语义，但具体运行要求差异很大。

因此 V1 必须采用：

- 通用资产 schema
- 家族特化字段

而不能假设所有模型都只需要“仓库地址 + 下载目录 + 必需文件列表”。

## 为什么必须读具体模型文档

代表模型已经证明，仅靠通用参数不足以支撑自动化安装：

- `Fun-ASR`
  - 支持 31 种语言。
  - 新版本支持说话人分离时，需要额外的 `vad_model`、`spk_model`、`punc_model`，并且 README 指出该能力要求从源码安装 `FunASR`。
  - 来源：[FunAudioLLM/Fun-ASR](https://github.com/FunAudioLLM/Fun-ASR)
- `Qwen3-ASR`
  - 同时存在 `0.6B`、`1.7B` 和 `Qwen3-ForcedAligner-0.6B`。
  - 官方支持 `qwen-asr`、`qwen-asr[vllm]`、Docker、FlashAttention 2。
  - 官方建议独立 Python 3.12 环境。
  - 来源：[QwenLM/Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)
- `MiMo-V2.5-ASR`
  - 除主模型外还依赖 `MiMo-Audio-Tokenizer`。
  - README 明确写了 Python 3.12、CUDA >= 12.0、`flash-attn==2.7.4.post1`，偏 Linux 路线。
  - 来源：[XiaomiMiMo/MiMo-V2.5-ASR](https://github.com/XiaomiMiMo/MiMo-V2.5-ASR)
- `CohereLabs/cohere-transcribe-03-2026`
  - 官方既支持 Transformers 本地推理，也支持 vLLM 服务化推理。
  - 还涉及 `AutoProcessor`、`CohereAsrForConditionalGeneration`、长音频分块、标点开关、`trust_remote_code` 等运行特征。
  - 来源：[模型卡](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026) [Transformers 文档](https://huggingface.co/docs/transformers/model_doc/cohere_asr)

结论：

- 需要抽象出统一 schema。
- 也必须保留每个模型家族的特化描述能力。

## TTS 代表样本补充

截至 2026-05-22，我额外检查了 Hugging Face `text-to-speech` 热门模型页，确认 `VoxCPM2` 和 `IndexTTS-2` 都位于当前热门列表中，`GPT-SoVITS` 虽然不一定处在最前排，但仍是非常有代表性的家族。

这些 TTS 样本对本系统的价值不在“是否最热门”，而在于它们覆盖了不同类型的资产管理难点：

- `VoxCPM2`
  - 代表“现代 Python 包直装 + 多运行后端 + 多版本并存 + 语音设计/克隆/流式”的家族。
- `GPT-SoVITS`
  - 代表“WebUI/脚本驱动 + 多预训练代际 + 外部二进制依赖 + 训练与推理共存”的家族。
- `IndexTTS-2`
  - 代表“严格环境管理 + Git LFS + 强依赖版本锁定 + 情绪控制能力”的家族。

来源：

- [Hugging Face TTS Trending](https://huggingface.co/models?pipeline_tag=text-to-speech&sort=trending)
- [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM)
- [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)
- [index-tts/index-tts](https://github.com/index-tts/index-tts)
- [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)

## 术语

### 模型家族

一组共享主要运行时依赖和加载方式的模型集合。

示例：

- `faster_whisper`
- `fun_asr`
- `qwen3_asr`
- `mimo_asr`
- `cohere_asr`

### 模型变体

同一家族内的具体模型规格或体量。

示例：

- `tiny / base / small / medium / large-v3`
- `Fun-ASR-Nano / Fun-ASR-MLT-Nano`
- `Qwen3-ASR-0.6B / Qwen3-ASR-1.7B`

### 附属资产

运行主模型所需或推荐配套的附加资源。

示例：

- tokenizer
- forced aligner
- VAD 模型
- speaker diarization 模型
- punctuation 模型
- remote code 文件

### 运行时配置档

一组描述模型运行所需环境的约束。

示例：

- Python 版本
- CPU/GPU 约束
- CUDA 约束
- 操作系统约束
- 是否推荐 Docker
- 是否支持 Windows 原生

### 下载模式

系统向用户暴露的安装粒度。

V1 至少支持：

- 单模型下载
- 推荐组合下载
- 同家族全部下载

## 用户故事

### 用户故事 1

用户在“模型资源”页选择某个 ASR 模型并点击下载，等待完成后，能够直接在任务流中选择该模型运行，无需额外操作。

### 用户故事 2

用户选择某个模型家族的推荐配置时，系统会自动安装主模型、必需依赖和推荐附属资产。

### 用户故事 3

用户希望一次性准备完整的某类模型能力时，可以执行“同家族全部下载”。

### 用户故事 4

当新模型未来被接入时，系统仍然复用同一套下载、校验、状态和前端交互逻辑。

## 核心需求

### 1. 资产元数据必须从“文件定义”升级为“安装定义”

当前 `models.yaml` 更像“权重目录清单”。

V1 之后每个条目至少应能描述：

- 模型所属家族
- 模型变体组
- 主模型仓库
- 附属资产列表
- 必需 Python 依赖或 extra
- 平台约束
- 推荐安装模式
- 安装后校验策略
- 是否允许自动下载远程代码

### 2. 系统必须识别共享依赖

V1 需要显式表达：

- 哪些依赖属于整个模型家族共享
- 哪些依赖只属于某个变体
- 哪些依赖是推荐而非必需

最少应支持三类依赖：

- `required_runtime_dependencies`
- `recommended_runtime_dependencies`
- `optional_runtime_dependencies`

### 3. 系统必须支持模型附属资产

V1 需要支持主模型之外的附属资产管理。

附属资产至少分三类：

- `required_assets`
- `recommended_assets`
- `optional_assets`

这类资产必须能参与：

- 下载
- 状态显示
- 安装后校验
- 删除

### 4. 系统必须支持下载模式

V1 至少需要这三种模式：

- `single`
  - 仅安装当前模型及其必需依赖、必需资产
- `recommended`
  - 安装当前模型及其推荐附属资产
- `family_all`
  - 安装该家族下所有官方支持变体，以及家族必需依赖

后续可扩展：

- `platform_optimized`
  - 例如优先下载 ONNX、GGUF、MLX 或 CoreML 变体

### 5. 必须定义“可直接使用”的验收标准

模型状态不能只通过“权重文件存在”判断。

V1 的最小验收标准：

- 必需权重已下载
- 必需附属资产已下载
- 必需 Python 依赖已可导入
- 平台约束满足
- provider 可完成最小加载
- provider 可对最小音频样例执行一次最小推理或 dry-run 校验

只有满足以上条件，状态才能进入 `ready`。

### 6. 必须定义环境策略

V1 需要明确不再让所有模型只依赖一个模糊的全局环境。

推荐 V1 策略：

- 采用“按模型家族共享环境”
- 暂不做“每模型独立环境”

原因：

- 比全局环境更容易表达共享依赖和冲突边界
- 比每模型独立环境更易实施
- 能覆盖大多数未来新增模型

### 7. 必须显式处理平台约束

有些模型并不是所有平台都能直接落地。

V1 必须允许模型条目声明：

- 支持的操作系统
- 支持的 Python 版本
- 是否要求 CUDA
- 最低 CUDA 版本
- 是否建议 Linux/Docker
- Windows 是否可直接支持

如果当前环境不满足要求，系统应：

- 阻止进入 `ready`
- 给出明确原因
- 提供可执行的替代建议

### 8. 必须支持版本和共存策略

V1 至少要明确以下规则：

- 权重变体可并存
- 附属资产可共享
- 家族依赖采用单版本策略
- 不支持同一家族 Python 包多版本并存

如果未来出现版本冲突，至少要能在元数据层表达：

- 冲突项
- 不兼容版本范围
- 替代安装路径

### 9. 必须支持状态可解释

当前状态管理需要从“missing / installed”提升为更完整的安装生命周期状态。

建议最少支持：

- `missing`
- `downloading`
- `installing_dependencies`
- `installing_assets`
- `verifying`
- `ready`
- `invalid`
- `unsupported`
- `error`

同时 detail 必须可解释：

- 缺什么
- 卡在哪一步
- 为什么不能直接使用

### 10. 前端必须表达“单模型 / 推荐 / 全部”

桌面页后续应支持：

- 查看模型家族
- 查看每个变体
- 查看附属资产
- 选择安装模式
- 查看预估下载体积
- 查看依赖安装说明
- 查看当前环境兼容性

V1 不要求前端重构完成，但后端契约必须先支持这一目标。

## 代表模型映射

### `faster_whisper`

特点：

- 家族结构简单
- 主要差异在模型大小
- 共享加载路径稳定
- 适合作为最基础的“单模型变体家族”样板

V1 归类建议：

- 家族共享环境
- 变体：`tiny/base/small/medium/large-v3`
- 默认支持 `single` 与 `family_all`

### `fun_asr`

特点：

- 存在多语言变体
- 远程代码与本地源码路径可能影响可用性
- 新能力可能引入额外附属模型

V1 归类建议：

- 家族共享环境
- 远程代码策略必须显式配置
- 将 `vad/spk/punc` 视为附属资产而非主模型本体

### `qwen3_asr`

特点：

- 主模型与 `forced aligner` 是天然关联但非完全同一资产
- 同时支持 transformers 和 vLLM 路线
- 官方明确建议独立环境和 FlashAttention 2

V1 归类建议：

- 主家族：`qwen3_asr`
- 推荐附属资产：`Qwen3-ForcedAligner-0.6B`
- 运行档至少区分：
  - `transformers_basic`
  - `vllm_streaming`

### `mimo_asr`

特点：

- 主模型外还需单独 tokenizer
- 对 Python/CUDA/平台约束更强
- 目前更像“高门槛家族”

V1 归类建议：

- 必须支持“主模型 + tokenizer”联装
- 必须支持平台约束拦截
- 可能需要标记为 `linux_preferred`

### `cohere_asr`

特点：

- 官方主路线是 Transformers
- 同时存在 vLLM 路线
- 社区已衍生 ONNX、GGUF、MLX、CoreML 等变体

V1 归类建议：

- 官方模型和社区衍生变体分开建模
- 官方模型优先作为 `primary_variant`
- 社区 ONNX/GGUF/MLX/CoreML 视为 `derived_variant`
- 需要支持“同一家族不同运行后端”

## 代表 TTS 模型映射

### `voxcpm`

特点：

- 官方直接提供 `pip install voxcpm` 路线。
- 明确声明运行要求：Python `>=3.10,<3.13`、PyTorch `>=2.5.0`、CUDA `>=12.0`。
- 同一家族内已有多个版本：`VoxCPM2`、`VoxCPM1.5`、`VoxCPM-0.5B`。
- 支持多种模式：
  - voice design
  - controllable voice cloning
  - prompt-based ultimate cloning
  - streaming
  - production serving
- 官方还给出了 `Nano-vLLM` 和 `vLLM-Omni` 路线。

V1 归类建议：

- 家族：`voxcpm`
- 变体组：`VoxCPM2 / VoxCPM1.5 / VoxCPM-0.5B`
- 运行档至少区分：
  - `python_local`
  - `nano_vllm`
  - `vllm_omni`
- 需要支持的附属输入不只是“模型权重”，还包括：
  - `reference_wav`
  - `prompt_wav`
  - `prompt_text`
  - 可选控制文本

它覆盖的需求点：

- 同一家族多版本共存
- 同一家族多后端运行
- 零样本克隆与声音设计
- 纯文本模式与参考音频模式共存

### `gpt_sovits`

特点：

- 不是单纯的推理模型，更像“训练 + 推理 + WebUI + 数据处理工具”综合系统。
- 零样本 TTS 需要约 5 秒参考音频。
- few-shot 微调可使用约 1 分钟训练数据。
- 跨语言推理支持英语、日语、韩语、粤语和中文。
- 环境与安装具有明显平台差异：
  - 提供 Linux / macOS 安装脚本
  - 支持 Docker
  - Windows 还需额外放置 `ffmpeg.exe` 和 `ffprobe.exe`
- 版本体系复杂：
  - v2
  - v3
  - v4
  - v2Pro / v2ProPlus
- 不同版本需要下载不同预训练资源，有的还引入：
  - `bigvgan`
  - 超分模型
  - 额外文本资源

V1 归类建议：

- 家族：`gpt_sovits`
- 变体组至少区分：
  - `v2_family`
  - `v3_family`
  - `v4_family`
  - `v2pro_family`
- 运行档至少区分：
  - `webui_local`
  - `api_local`
  - `docker`
- 附属资产必须支持：
  - 预训练模型包
  - 外部二进制工具
  - 可选超分模型
  - 可选文本前端资源

它覆盖的需求点：

- 多代预训练资产并存
- 平台特有外部工具依赖
- 推理模型与训练工具链耦合
- 不是所有“模型可用”都等于“单步 API 可用”

### `indextts`

特点：

- `IndexTTS-2` 当前主打高表现力零样本 TTS 和时长控制。
- 官方明确要求：
  - `git`
  - `git-lfs`
  - `uv`
- 官方甚至明确表示只支持 `uv` 安装方式，`pip/conda` 不保证依赖正确。
- 安装命令是 `uv sync --all-extras`，之后再用 `hf download` 或 `modelscope download` 拉权重到 `checkpoints`。
- 还支持情绪控制相关参数，例如：
  - `use_emo_text`
  - `emo_alpha`
  - `emo_text`

V1 归类建议：

- 家族：`indextts`
- 变体组：`IndexTTS / IndexTTS-1.5 / IndexTTS-2`
- 运行档至少区分：
  - `uv_project_local`
- 附属能力需要支持：
  - 情绪描述输入
  - 时长控制能力声明

它覆盖的需求点：

- 强约束的环境管理器
- Git LFS 作为前置条件
- 项目级 `.venv` 与权重目录并存
- 文本情绪控制类运行时参数

### `kokoro`

特点：

- `Kokoro-82M` 是轻量级本地 TTS，模型卡标注为 82M 参数。
- 官方使用方式是直接安装 `kokoro` Python 包并通过 `KPipeline` 本地推理。
- 除 Python 依赖外，还需要系统侧 `espeak-ng`。
- 底层还依赖 `misaki` 这类 G2P 组件。
- 仍然属于 `PyTorch` 主线，不需要引入额外轻量格式生态。

V1 归类建议：

- 家族：`kokoro`
- 运行档：`python_package_local`
- 适合作为“轻量本地 TTS 样本”
- 适合作为“点击下载后快速可用”的体验基线

它覆盖的需求点：

- 小权重本地模型
- Python 包直装
- 系统工具前置依赖
- G2P 类附属运行组件

## 对通用 schema 的新增启发

加入 TTS 代表模型后，通用 schema 需要补充下面几类字段。

### 参考输入能力

- `supports_reference_audio`
- `supports_prompt_audio`
- `supports_prompt_text`
- `supports_voice_design_text`

### 控制能力

- `supports_style_control`
- `supports_emotion_control`
- `supports_duration_control`
- `supports_streaming_tts`

### 外部工具与前置条件

- `required_system_tools`
- `required_binary_assets`
- `required_vcs_features`

例如：

- `ffmpeg`
- `ffprobe`
- `git`
- `git-lfs`
- `espeak-ng`

### 运行档类型

除了原先偏 ASR 的本地推理档，还应显式支持：

- `python_package_local`
- `project_venv_local`
- `webui_local`
- `docker_runtime`
- `vllm_service`

### 资产类别

对 TTS 来说，附属资产不应只理解为 tokenizer 或对齐器，还应包括：

- vocoder
- super-resolution model
- speaker encoder
- text frontend resources
- pretrained checkpoint bundle
- optional fine-tune assets

## 推荐的元数据字段

V1 建议在当前模型注册表基础上新增如下字段。

### 家族与变体

- `family_id`
- `variant_group`
- `variant_tier`
- `is_primary_variant`

### 下载与安装

- `install_modes`
- `download_sources`
- `auto_install_dependencies`
- `allow_remote_code`

### 依赖

- `dependency_group`
- `required_python_extras`
- `required_runtime_packages`
- `recommended_runtime_packages`
- `conflicts`

### 资产

- `required_assets`
- `recommended_assets`
- `optional_assets`

### 平台与环境

- `runtime_profile`
- `supported_os`
- `supported_python`
- `requires_gpu`
- `min_cuda`
- `preferred_runtime`

### 校验

- `post_install_checks`
- `sample_inference_policy`
- `healthcheck_timeout_seconds`

## 推荐的安装契约

### 后端输入

现有安装接口建议扩展为可表达安装模式和联装策略。

建议新增字段：

- `install_mode`
- `install_dependencies`
- `install_recommended_assets`
- `allow_fallback_variant`

### 后端行为

安装流程建议统一为：

1. 解析模型条目
2. 解析模型家族与运行档
3. 检查平台约束
4. 安装必需依赖
5. 下载主模型权重
6. 下载必需附属资产
7. 按模式下载推荐资产
8. 执行安装后校验
9. 写入最终状态

### 删除行为

删除也应区分粒度：

- 删除当前模型权重
- 删除当前模型及其独占资产
- 保留共享依赖

V1 不建议默认删除家族共享依赖。

## 非目标

V1 不要求：

- 立即支持每模型独立虚拟环境
- 立即支持跨机器同步模型缓存
- 立即支持下载进度断点续传编排
- 立即覆盖所有社区量化变体
- 立即覆盖非 `PyTorch` 主线的本地运行格式

## 实施建议

### 第一阶段

- 定义统一元数据 schema
- 为现有 `faster_whisper`、`fun_asr`、`qwen3_asr` 补齐家族信息
- 将 `voxcpm`、`gpt_sovits`、`indextts`、`kokoro` 作为 TTS 侧代表样本固化进 schema 设计
- 将“手工安装 extra”升级为后端可选自动安装

### 第二阶段

- 增加附属资产管理
- 增加安装模式
- 增加强约束的平台检查

### 第三阶段

- 接入 `MiMo-V2.5-ASR`
- 接入 `cohere-transcribe-03-2026`
- 评估是否需要家族级独立环境

## 一句话结论

模型资产管理 V1 的核心不是“让系统会下载模型”，而是“让系统理解模型家族、依赖、附属资产、平台约束和安装后可用性，并把这些复杂度从用户手上拿走”。
