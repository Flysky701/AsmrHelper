# 功能 11：LLM 能力管理与衍生操作管理 V1 计划

## 目标

- 将当前系统中的翻译、脚本清洗、LLM 对齐、文本重写等能力统一收口为 LLM 主干能力下的衍生操作。
- 明确“翻译”不是独立引擎层，而是 LLM provider 能力的一种典型应用。
- 为后续字幕翻译、文本清洗、提示词驱动的结构化处理建立统一的 LLM 业务边界。

## 背景

- 当前仓库中，LLM provider 已经通过配置和模型管理存在：
  - `src/config.py`
  - `src/core/model_manager.py`
  - `src/core/resources/model_catalog.py`
- 当前系统中与 LLM 直接相关的业务并不只包含翻译，还包括：
  - `src/app/services/translation_service.py` 的独立翻译
  - `src/app/services/audio_tool_service.py` 的字幕翻译
  - `src/core/subtitles/script_to_subtitle.py` 与 `src/core/subtitles/script_tool.py` 中的脚本清洗与智能对齐入口
  - `src/app/services/script_subtitle_service.py` 的 `use_llm_clean`
- 当前如果继续使用“翻译引擎”这一命名，会带来两个问题：
  - 把 LLM 的能力边界说窄了
  - 让后续的清洗、重写、对齐、结构化任务各自发展出一套 provider 管理逻辑

## 功能定位

功能 11 是 LLM provider 级功能域。

它负责：

1. 管理系统中的 LLM provider 与模型选择。
2. 定义所有 LLM provider 共享的通用能力边界。
3. 管理基于 LLM 的衍生操作类型。
4. 为功能 7、功能 4、功能 2 提供统一的 LLM 能力消费入口。

它不把“翻译”定义为独立主干功能，而是把翻译视为 LLM 衍生操作之一。

## 与其他功能的关系

### 与功能 6 的关系

- 功能 6 负责 provider 参数 schema、默认值、`CapabilityDescriptor` 和 `ExecutionProfile` 规则。
- 功能 11 负责 LLM provider 的业务能力边界，以及不同衍生操作如何消费这些能力。

### 与功能 5 的关系

- 功能 5 负责运行前提、云端配置可用性和本地资源条件检查。
- 功能 11 负责声明不同 LLM 操作依赖哪些 provider 能力和模型能力。

### 与功能 7 的关系

- 功能 7 负责字幕与文本资产本体。
- 功能 11 为功能 7 提供：
  - 字幕翻译
  - 文本清洗
  - 文本重写
  - 对齐辅助

### 与功能 4 的关系

- 功能 4 的 `tool.translate_subtitle`、未来 `tool.text_rewrite`、`tool.subtitle_clean` 等只是一层工具任务入口。
- 真正的 LLM 衍生操作语义归属功能 11。

### 与功能 2 的关系

- 功能 2 的 `translation_profile` 不应被理解为“翻译引擎”。
- 它本质上应是一个 LLM profile，供单任务流水线在翻译阶段消费。

## 边界

### 本功能负责

- LLM provider 注册与能力声明
- LLM 通用调用边界
- LLM 衍生操作类型定义
- 不同 LLM 操作与 provider capability 的映射
- LLM 类结果与错误语义的统一方向

### 本功能不负责

- 不负责全局 provider 参数 schema 定义，这属于功能 6
- 不负责字幕资产模型，这属于功能 7
- 不负责任务排队和调度，这属于功能 3
- 不负责完整流水线编排，这属于功能 2
- 不负责把所有 LLM 操作都立即展开成独立重功能

## 核心原则

### 1. 翻译不是独立引擎层

V1 需要明确：

- “翻译 provider”这个说法只适合兼容旧接口
- 真正稳定的一层是 `llm` provider
- 翻译只是 LLM 最常见的衍生操作之一

### 2. LLM 主干能力和衍生操作必须分开

V1 需要明确区分：

- **通用能力**
  - messages / prompt 输入
  - model 选择
  - temperature
  - max tokens
  - structured output 能力
  - system prompt / user prompt 角色语义

- **衍生操作**
  - 翻译
  - 文本清洗
  - 文本重写
  - 字幕对齐辅助
  - 结构化提取
  - 未来更多 prompt-driven 操作

### 3. 操作类型必须显式声明

每类 LLM 衍生操作都需要明确其目标，而不是只在代码里散落若干 prompt。

建议至少定义操作类型：

- `translate`
- `subtitle_translate`
- `script_clean`
- `subtitle_clean_assist`
- `subtitle_align`
- `text_rewrite`
- `structured_extract`

## V1 需要实现的功能

### 1. LLM provider 注册表

V1 需要建立独立的 LLM provider 注册与能力声明。

建议至少定义：

- `provider_id`
- `display_name`
- `available`
- `supported_models`
- `capabilities`
- `default_model`

其中 `capabilities` 至少可描述：

- `chat_completion`
- `structured_output`
- `json_mode`
- `long_context`
- `streaming`

### 2. LLM 通用执行接口

V1 需要有统一 LLM 执行入口，避免各业务模块直接拼接 provider 调用细节。

统一接口至少应支持：

- 系统提示词
- 用户输入
- model
- 通用 options
- provider options

### 3. LLM 衍生操作注册

V1 需要定义 LLM 衍生操作的注册或映射层。

目的：

- 明确每个操作用什么 prompt 策略
- 明确每个操作是否需要结构化输出
- 明确每个操作的输入和输出约束

例如：

- `subtitle_translate` 要求逐段输出并保持顺序
- `script_clean` 要求移除舞台说明并保留可读对白
- `subtitle_align` 要求对齐脚本与 ASR 结果并返回时间轴结构

### 4. 翻译能力降级为 LLM 操作

V1 需要在文档和架构上明确：

- `TranslationService` 可以暂时保留为兼容 facade
- 但它的长期归属应被视为 LLM 衍生操作 facade
- `translate_provider` 这类旧字段后续应逐步迁移为标准化 LLM profile

### 5. LLM 文本后处理能力

V1 应确认以下能力属于功能 11，可逐步接入但不要求同轮全部重构：

- 字幕翻译
- 脚本清洗
- 脚本与字幕对齐辅助
- 文本重写
- 术语提示与术语约束
- 质量检查辅助

## API 设计

### 通用 LLM 能力 API

- `GET /api/v1/llm/providers`
- `GET /api/v1/llm/providers/{provider_id}`
- `POST /api/v1/llm/operations/run`

用途：

- 查询 LLM provider 能力
- 执行标准化 LLM 衍生操作

### 兼容现有接口

当前可兼容保留：

- `POST /api/v1/translation/translate`
- `POST /api/v1/tools/translate-subtitle`
- `POST /api/v1/subtitles/script-to-vtt` 中的 LLM 清洗路径

但文档上应明确：

- 这些只是 LLM 衍生操作的旧入口
- 长期不应继续主导功能边界

## 中间层设计

### `LlmProviderRegistryService`

职责：

- 管理 LLM provider 注册表
- 暴露 provider 能力描述

### `LlmExecutionService`

职责：

- 统一发起 LLM 调用
- 屏蔽 provider 差异

### `LlmOperationRegistryService`

职责：

- 注册衍生操作类型
- 维护操作到 prompt / 输出约束 / capability 需求的映射

### `LlmDerivedOperationService`

职责：

- 承接翻译、清洗、重写、对齐等具体衍生操作
- 作为当前 `TranslationService` 等 facade 的长期收口层

## 与当前实现的关系

### 可以保留的思路

- `ModelManager` 里按 `llm` category 管理 provider 的方向
- `TranslationService` 作为兼容 facade 的方向
- `core/subtitles` 中将脚本清洗、对齐等 prompt 驱动操作独立出来的方向
- `terminology.py`、`quality.py` 这类文本处理辅助模块的积累

### 必须重组或迁移的部分

- “翻译 provider”不应继续作为主边界命名
- `translate_provider` 之类平铺字段后续应迁移为 LLM profile
- `script_clean`、`llm_align` 这类能力不应继续仅作为脚本转字幕的内部细节存在
- 各业务模块不应继续直接理解 provider 差异

### 明确不继承的历史包袱

- 不继承“翻译就是一个独立引擎层”的认知
- 不继承“每种 LLM 文本处理动作都各自管理 provider”的方式
- 不继承“prompt 逻辑只散落在业务代码里”的方式

## V1 内必须落地

1. 明确 LLM 主干能力边界
2. 明确翻译属于 LLM 衍生操作
3. 建立 LLM provider 与衍生操作的映射思路
4. 将当前翻译、脚本清洗、对齐辅助归入同一能力域

## V1 内暂不落地

1. 不在这一轮统一所有 LLM 操作结果结构
2. 不在这一轮重做全部 prompt 体系
3. 不在这一轮做复杂 agentic LLM 工作流
4. 不在这一轮保证所有 provider 支持同样的衍生操作

## 一句话结论

功能 11 可以正式定义为：

> LLM 能力管理与衍生操作管理 = 统一管理 LLM provider 的通用能力，并将翻译、清洗、重写、对齐等文本处理任务收口为 LLM 衍生操作，而不是为每种操作单独建立引擎层。
