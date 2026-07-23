# [已归档] 功能 12：ASR 引擎管理与扩展能力管理 V1 计划

## 目标

- 将当前系统中的 ASR 能力从“现有识别实现 + 工具入口 + pipeline 阶段参数”的混合状态，整理为统一的 ASR 引擎管理功能域。
- 明确哪些能力属于所有 ASR 引擎共享的通用识别能力，哪些能力只是某些引擎的扩展能力。
- 为后续支持多个识别引擎预留稳定边界，避免把当前 `faster_whisper` 的实现细节写死成产品主干。

## 背景

- 当前仓库已经存在稳定的 ASR 应用入口：
  - `src/app/services/asr_service.py`
  - `src/api/http/routes/asr.py`
- 当前底层识别主要由：
  - `src/core/asr/__init__.py`
  - `src/core/model_manager.py`
  - `src/core/resources/model_installer.py`
  这一层支撑，且明显已经具备“引擎层”事实。
- 当前系统中与 ASR 相关的配置与调用点包括：
  - `processing.asr_model`
  - `language`
  - `disable_vad`
  - pipeline 中的 `asr` 阶段
  - 工具页中的 `tool.asr`
  - `script_to_subtitle` 中的 ASR 识别阶段
- 当前虽然主要只有 `faster_whisper` 一种识别实现，但你已经明确后续会支持多个识别引擎，因此不能把现在的单引擎状态当成最终边界。

## 功能定位

功能 12 是 ASR provider 级功能域。

它负责：

1. 管理系统中的 ASR 引擎注册与能力声明。
2. 定义所有 ASR 引擎共享的通用识别能力边界。
3. 挂接某些引擎专属的扩展能力。
4. 为功能 2、功能 4、功能 7 提供统一的 ASR 能力消费接口。

它不把“当前只有 faster_whisper”视为产品边界，而把它视为当前已接入的一个 ASR 引擎实现。

## 与其他功能的关系

### 与功能 6 的关系

- 功能 6 负责 provider 参数 schema、默认值、`CapabilityDescriptor` 和 `ExecutionProfile` 规则。
- 功能 12 负责 ASR 引擎的业务能力边界与具体接入方式。
- 换句话说：
  - 功能 6 负责“参数长什么样”
  - 功能 12 负责“这个 ASR 引擎实际上能识别什么、支持什么行为”

### 与功能 5 的关系

- 功能 5 负责本地模型、运行资源、可执行性检查。
- 功能 12 负责告诉功能 5：某个 ASR 引擎依赖哪些模型、运行时库和设备条件。

### 与功能 4 的关系

- 功能 4 的 `tool.asr` 只是一层工具任务入口。
- 真正的 ASR 执行业务逻辑与引擎分发归属功能 12。

### 与功能 2 的关系

- 功能 2 中的 `asr_profile` 不应直接面向某个具体类或当前实现细节。
- 功能 2 只消费功能 12 暴露的标准 ASR 能力。

### 与功能 7 的关系

- 功能 7 负责字幕与文本资产。
- 功能 12 负责把音频识别成可供功能 7 消费的文本片段、时间轴片段和识别结果资产。

## 边界

### 本功能负责

- ASR 引擎注册与能力声明
- ASR 通用识别能力定义
- ASR 执行器或 provider adapter 管理
- 引擎专属扩展能力挂接
- 识别结果的引擎侧语义边界

### 本功能不负责

- 不负责全局 provider 参数 schema 定义，这属于功能 6
- 不负责字幕资产模型定义，这属于功能 7
- 不负责任务排队，这属于功能 3
- 不负责完整流水线编排，这属于功能 2
- 不负责把某个引擎的私有选项强行写成所有 ASR 的通用能力

## 核心原则

### 1. ASR 通用能力和扩展能力必须分开

V1 需要明确区分：

- **通用能力**
  - 音频转写
  - 语言指定或自动检测
  - 时间轴分段输出
  - 文本输出
  - 可选字幕导出

- **扩展能力**
  - VAD 开关与 VAD 参数细化
  - domain prompt / initial prompt
  - speaker diarization
  - word-level timestamps
  - confidence scores
  - 设备选择策略
  - streaming recognition

只有通用能力才允许作为跨引擎稳定契约。

### 2. 当前实现不能等同于最终边界

V1 需要明确：

- 当前 `faster_whisper` 只是一个已接入的 ASR 引擎
- `model_size`、`disable_vad`、`initial_prompt` 等不一定是所有引擎共享的稳定字段
- 后续新增引擎时，不应该被迫适配当前实现的全部私有参数命名

### 3. 引擎能力必须显式声明

每个 ASR 引擎都必须给出能力描述，而不能靠页面或 pipeline 逻辑猜测。

建议至少声明：

- 是否支持 `language_hint`
- 是否支持 `language_auto_detect`
- 是否支持 `vad`
- 是否支持 `word_timestamps`
- 是否支持 `diarization`
- 是否支持 `confidence`
- 是否支持 `initial_prompt`
- 是否支持 `streaming`

## V1 需要实现的功能

### 1. ASR 引擎注册表

V1 需要建立独立于通用 provider schema 的 ASR 引擎注册表。

建议至少定义：

- `engine_id`
- `display_name`
- `kind`
- `available`
- `capabilities`
- `supported_models`
- `default_language_mode`

其中 `kind` 至少区分：

- `local`
- `cloud`
- `hybrid`

### 2. ASR 通用执行接口

V1 需要统一 ASR 执行入口，不再让各调用方直接理解底层实现。

统一接口至少应覆盖：

- 音频输入
- model 选择
- language 或 auto
- 输出文本
- 输出 segments
- 可选字幕导出

### 3. ASR 引擎扩展能力声明

V1 需要允许每个引擎额外挂接扩展能力。

例如某个引擎可能支持：

- `vad_control`
- `initial_prompt`
- `word_timestamps`
- `confidence_scores`

另一个引擎可能支持：

- `diarization`
- `streaming`

而某些简单引擎可能只支持：

- `basic_transcription`

这部分必须显式暴露给功能 6 和前端，而不是硬编码在工具页或 pipeline 参数里。

### 4. ASR 结果基础对象

V1 可以先明确一层最基础的引擎输出对象，但不要求所有引擎完全同构。

例如：

- `AsrTranscriptResult`
- `AsrSegmentResult`
- `AsrSubtitleExportResult`

注意：

- 这些是 ASR 侧输出对象
- 最终任务结果产物仍由功能 8 统一索引

### 5. ASR 预处理与识别策略挂接

V1 允许某些引擎声明识别前后处理能力，例如：

- 轻声识别提示
- VAD 策略
- 语言归一化
- 输出分段策略

但这些必须通过 capability 和 provider options 显式暴露，不能继续默认写死在调用方里。

## API 设计

### 通用 ASR API

- `POST /api/v1/asr/transcribe`
- `GET /api/v1/asr/engines`
- `GET /api/v1/asr/engines/{engine_id}`

用途：

- 提供 ASR 通用识别与引擎能力查询

### 扩展能力说明

当前不建议为每个 ASR 扩展能力立即单独暴露一堆 API。

V1 更适合：

- 先通过 capability descriptor 暴露能力
- 再由功能 6 和前端按需渲染参数区
- 由标准 `ExecutionProfile` 携带通用参数与引擎扩展参数

## 中间层设计

### `AsrEngineRegistryService`

职责：

- 管理 ASR 引擎注册表
- 提供引擎能力查询
- 为调用方暴露 ASR capability

### `AsrEngineExecutionService`

职责：

- 执行通用 ASR 转写
- 根据 `ExecutionProfile` 分发到正确引擎

### `AsrExtensionCapabilityService`

职责：

- 管理 VAD、prompt、word timestamps、diarization 等扩展能力
- 判断某个引擎是否支持某项扩展能力

### `AsrResultAdapterService`

职责：

- 将不同引擎返回的识别结果收敛为系统可消费的基础 ASR 输出对象

## 与当前实现的关系

### 可以保留的思路

- `AsrService` 作为稳定应用入口的方向
- `ASRRecognizer` 作为当前引擎实现的方向
- `ModelManager` 中按 `asr` category 管理 provider 的方向
- `model_installer` 中的 whisper 模型安装思路

### 必须重组或迁移的部分

- 当前 `asr_model`、`language`、`disable_vad` 等字段后续应迁移为标准化 `asr_profile`
- pipeline 和工具页不应继续直接拥有 ASR 引擎私有参数语义
- 当前“只有一个 ASR 引擎”的事实不能被写进长期功能边界

### 明确不继承的历史包袱

- 不继承“ASR 就等于 faster_whisper”的认知
- 不继承“当前工具表单字段就是未来所有 ASR 通用字段”的认知
- 不继承“pipeline 私有参数直接等于 ASR 产品能力边界”的方式

## V1 内必须落地

1. 明确 ASR 通用能力边界
2. 建立 ASR 引擎能力声明
3. 将当前 ASR 实现视为一个已接入引擎，而不是唯一产品形态
4. 为后续新增多个识别引擎留出稳定接口

## V1 内暂不落地

1. 不在这一轮接入多个新 ASR 引擎
2. 不在这一轮统一所有引擎的高级输出结构
3. 不在这一轮做复杂 diarization 工作流
4. 不在这一轮做 streaming ASR 产品化

## 一句话结论

功能 12 可以正式定义为：

> ASR 引擎管理与扩展能力管理 = 统一管理 ASR 引擎的通用识别能力与引擎专属扩展能力，并为后续支持多个识别引擎保留稳定边界，而不把当前单引擎实现写死成产品主干。
