# AsmrHelper 中间层 Service 映射总表 V1

## 目标

- 将当前仓库里的应用层 service、核心入口和未来功能域之间的关系一次性收口。
- 明确每个功能域未来应该有哪些中间层 service。
- 明确现有 service 哪些可以保留，哪些需要拆分，哪些只是兼容层。

## 使用原则

这份文档不直接定义 API，也不直接定义底层算法实现。

它回答的是：

- 功能域在代码里应该落成哪些 service
- 这些 service 的职责边界是什么
- 当前已有代码应该迁去哪里

## 当前应用层现状

当前 `src/app/services` 主要包括：

- `asr_service.py`
- `audio_tool_service.py`
- `batch_pipeline_service.py`
- `model_service.py`
- `pipeline_service.py`
- `resource_service.py`
- `script_subtitle_service.py`
- `subtitle_service.py`
- `task_service.py`
- `translation_service.py`
- `tts_service.py`
- `voice_service.py`

当前这些 service 的共同问题是：

- 多数是“单接口 facade”，但还没有和新功能域一一对齐
- 部分 service 同时承担了兼容入口、业务逻辑拼装、结果组织三种职责
- 一些 service 的命名还带着旧页面或旧能力边界

## 处理方式分类

后续对现有 service 的处理统一按 4 类理解：

### 1. 保留

方向基本正确，只需要继续演化。

### 2. 拆分

当前职责过大，需要拆成多个 service。

### 3. 迁移

当前能力真实存在，但应归到另一个功能域。

### 4. 兼容层

短期可以保留，但长期不再作为主架构核心。

## 功能 1：工作空间与输入管理

### 目标 service

- `WorkspaceService`
- `InputCatalogService`
- `SessionService`

### 职责

- `WorkspaceService`
  - 解析工作空间目录
  - 解析默认输出、临时、模型目录
- `InputCatalogService`
  - 路径标准化
  - 输入类型识别
  - 伴随资源发现
- `SessionService`
  - 生成 `ProcessingSession`
  - 固化输入与输出上下文

### 当前代码映射

- `resource_service.py`
  - 处理方式：**拆分**
  - 说明：其中 workspace / output / temp 目录准备部分应迁入 `WorkspaceService`
- `src/utils/find_subtitle_file`
  - 处理方式：**迁移**
  - 说明：后续应归到 `InputCatalogService`

## 功能 2：单任务音频汉化流水线编排执行器

### 目标 service

- `PipelineTaskOrchestrator`
- `PipelineStepPlanner`
- `PipelineArtifactService`
- `PipelineExecutionContextBuilder`

### 职责

- `PipelineTaskOrchestrator`
  - 读取任务
  - 装载 session
  - 编排单个 `pipeline` 任务
- `PipelineStepPlanner`
  - 根据 `ExecutionProfile` 生成阶段计划
- `PipelineArtifactService`
  - 收集并组织 pipeline 产物
- `PipelineExecutionContextBuilder`
  - 把 session、profile、runtime binding 组合成执行上下文

### 当前代码映射

- `pipeline_service.py`
  - 处理方式：**拆分**
  - 说明：当前过于中心化，应拆入上面 4 个方向
- `batch_pipeline_service.py`
  - 处理方式：**迁移**
  - 说明：批量逻辑不属于功能 2，应迁回功能 3
- `src/core/pipeline/*`
  - 处理方式：**保留并重组**
  - 说明：底层 pipeline 执行能力可保留，但上层职责要重排

## 功能 3：统一任务生成与任务队列

### 目标 service

- `TaskSpecFactory`
- `TaskQueueService`
- `TaskDispatchService`
- `TaskQueryService`
- `TaskResultLinkService`

### 职责

- `TaskSpecFactory`
  - 生成标准任务定义
- `TaskQueueService`
  - 入队、出队、取消、重试、并发控制
- `TaskDispatchService`
  - 按 `task_type` 分发执行器
- `TaskQueryService`
  - 查询任务状态、列表、快照
- `TaskResultLinkService`
  - 维护任务与结果资产之间的关联

### 当前代码映射

- `task_service.py`
  - 处理方式：**拆分**
  - 说明：当前只是轻量状态表，不足以承接统一任务系统
- `batch_pipeline_service.py`
  - 处理方式：**迁移**
  - 说明：批量任务生成能力应落到这里
- 前端本地 task 状态逻辑
  - 处理方式：**迁移**
  - 说明：不应继续由页面自己维护任务体系

## 功能 4：单步工具执行体系

### 目标 service

- `ToolRegistry`
- `ToolExecutionService`
- 各工具执行器

### 目标执行器

- `SeparationToolExecutor`
- `ConvertToolExecutor`
- `SplitToolExecutor`
- `SubtitleTranslateToolExecutor`
- `AsrToolExecutor`
- `TtsToolExecutor`
- `ScriptSubtitleToolExecutor`
- `VolumePreviewToolExecutor`

### 职责

- `ToolRegistry`
  - 注册工具类型与执行器映射
- `ToolExecutionService`
  - 承接标准工具运行请求
- 各执行器
  - 只负责各自业务能力

### 当前代码映射

- `audio_tool_service.py`
  - 处理方式：**拆分**
  - 说明：当前聚合了多个工具能力，后续应拆成工具执行器集合
- `asr_service.py`
  - 处理方式：**兼容层**
  - 说明：当前可作为工具入口 facade 保留，但长期应由功能 12 驱动
- `tts_service.py`
  - 处理方式：**兼容层**
  - 说明：当前可作为工具入口 facade 保留，但长期应由功能 10 驱动
- `translation_service.py`
  - 处理方式：**兼容层**
  - 说明：当前可作为工具入口 facade 保留，但长期应由功能 11 驱动
- `script_subtitle_service.py`
  - 处理方式：**迁移**
  - 说明：业务本体应回归功能 7

## 功能 5：模型与运行资源管理

### 目标 service

- `ModelRegistryService`
- `RuntimeResourceService`
- `TaskReadinessService`

### 职责

- `ModelRegistryService`
  - 模型注册、状态、安装、校验、卸载
- `RuntimeResourceService`
  - 路径、目录、设备、运行资源检查
- `TaskReadinessService`
  - 根据任务和 profile 判断是否可执行

### 当前代码映射

- `model_service.py`
  - 处理方式：**保留并扩展**
  - 说明：方向基本正确，但要升级为 registry / lifecycle 层
- `resource_service.py`
  - 处理方式：**拆分**
  - 说明：运行资源能力与 workspace 能力需要分开
- `src/core/resources/*`
  - 处理方式：**保留并重组**

## 功能 6：配置与提供方接入管理

### 目标 service

- `SettingsService`
- `ProviderConfigService`
- `ConfigOverlayService`
- `CapabilityDescriptorService`
- `ExecutionProfileBuilder`

### 职责

- `SettingsService`
  - 配置读写与脱敏输出
- `ProviderConfigService`
  - provider 接入配置管理
- `ConfigOverlayService`
  - 默认值、文件、环境变量、运行时覆盖叠加
- `CapabilityDescriptorService`
  - 暴露能力描述
- `ExecutionProfileBuilder`
  - 构建标准 profile

### 当前代码映射

- `src/config.py`
  - 处理方式：**拆分**
  - 说明：当前读写能力可以保留，但职责要拆入上述服务
- `Settings.tsx` 当前本地 state 模式
  - 处理方式：**迁移**
  - 说明：前端不再主导配置事实

## 功能 7：字幕与文本资产管理

### 目标 service

- `SubtitleAssetService`
- `SubtitleParserService`
- `SubtitleNormalizationService`
- `SubtitleAlignmentService`
- `SubtitleExportService`
- `ScriptSubtitleDomainService`

### 职责

- `SubtitleAssetService`
  - 定义字幕和文本资产
- `SubtitleParserService`
  - 解析 SRT / VTT / LRC / 文本
- `SubtitleNormalizationService`
  - 清洗、规范化
- `SubtitleAlignmentService`
  - 双语字幕组装、对齐
- `SubtitleExportService`
  - 导出不同格式
- `ScriptSubtitleDomainService`
  - 处理脚本转字幕领域逻辑

### 当前代码映射

- `subtitle_service.py`
  - 处理方式：**保留并扩展**
  - 说明：可作为字幕资产层起点
- `script_subtitle_service.py`
  - 处理方式：**迁移并拆分**
  - 说明：应用入口可保留，领域逻辑应沉到功能 7
- `src/core/translate/*` 中字幕加载与清洗逻辑
  - 处理方式：**迁移**
- `src/core/subtitle_generator.py`
  - 处理方式：**迁移**
- `src/core/script_to_subtitle/*`
  - 处理方式：**迁移并重组**

## 功能 8：结果资产与产物索引管理

### 目标 service

- `ArtifactModelService`
- `ArtifactIndexService`
- `ArtifactPolicyService`

### 职责

- `ArtifactModelService`
  - 构建统一 `Artifact`
- `ArtifactIndexService`
  - 组织 `ArtifactSet`
- `ArtifactPolicyService`
  - 主产物判定与产物状态规则

### 当前代码映射

- `src/core/pipeline/artifact_collector.py`
  - 处理方式：**迁移并扩展**
  - 说明：应升级为统一产物索引能力
- pipeline / tool 各自返回的 `artifacts`
  - 处理方式：**收口**

## 功能 9：结果预览、浏览与人工校对

### 目标 service

- `PreviewService`
- `ReviewMarkerService`

### 职责

- `PreviewService`
  - 组织轻量预览包
- `ReviewMarkerService`
  - 管理 `accepted / needs_review / needs_rework`
  - 保存简短备注

### 当前代码映射

- 当前播放器与结果 UI 骨架
  - 处理方式：**兼容消费层**
  - 说明：页面可保留，但不应定义结果模型

## 功能 10：TTS 引擎管理与扩展能力管理

### 目标 service

- `TtsEngineRegistryService`
- `TtsEngineExecutionService`
- `TtsExtensionCapabilityService`
- `VoiceExtensionService`

### 职责

- `TtsEngineRegistryService`
  - 注册 TTS 引擎与能力
- `TtsEngineExecutionService`
  - 通用 TTS 合成分发
- `TtsExtensionCapabilityService`
  - 管理 profile / clone / preview 等扩展能力
- `VoiceExtensionService`
  - 收口当前 voice/profile 相关扩展逻辑

### 当前代码映射

- `tts_service.py`
  - 处理方式：**保留为兼容 facade**
- `voice_service.py`
  - 处理方式：**迁移为扩展能力层**
- `src/core/tts/*`
  - 处理方式：**保留并重组**

## 功能 11：LLM 能力管理与衍生操作管理

### 目标 service

- `LlmProviderRegistryService`
- `LlmExecutionService`
- `LlmOperationRegistryService`
- `LlmDerivedOperationService`

### 职责

- `LlmProviderRegistryService`
  - 管理 LLM provider 与模型能力
- `LlmExecutionService`
  - 发起统一 LLM 调用
- `LlmOperationRegistryService`
  - 注册翻译、清洗、重写、对齐等衍生操作
- `LlmDerivedOperationService`
  - 承接具体 LLM 文本任务

### 当前代码映射

- `translation_service.py`
  - 处理方式：**兼容 facade**
- `src/core/translate/*`
  - 处理方式：**拆分并迁移**
  - 说明：其中纯 LLM 调用和翻译逻辑应归功能 11，字幕领域逻辑归功能 7
- `src/core/script_to_subtitle/llm_processor.py`
  - 处理方式：**迁移**
  - 说明：应归为 LLM 衍生操作层

## 功能 12：ASR 引擎管理与扩展能力管理

### 目标 service

- `AsrEngineRegistryService`
- `AsrEngineExecutionService`
- `AsrExtensionCapabilityService`
- `AsrResultAdapterService`

### 职责

- `AsrEngineRegistryService`
  - 注册 ASR 引擎与能力
- `AsrEngineExecutionService`
  - 分发通用 ASR 转写
- `AsrExtensionCapabilityService`
  - 管理 VAD、prompt、word timestamps 等扩展能力
- `AsrResultAdapterService`
  - 统一不同引擎识别结果的系统可消费形态

### 当前代码映射

- `asr_service.py`
  - 处理方式：**保留为兼容 facade**
- `src/core/asr/*`
  - 处理方式：**保留并重组**
- `ModelManager` 中的 ASR category
  - 处理方式：**保留并规范化**

## 当前最关键的迁移结论

### 1. 现有应用层 facade 不等于最终功能域 service

例如：

- `translation_service.py`
- `tts_service.py`
- `asr_service.py`

这些当前可以保留，但更适合作为兼容入口，而不是长期主干 service。

### 2. 需要重点拆分的 service

优先级最高的拆分对象：

- `pipeline_service.py`
- `audio_tool_service.py`
- `task_service.py`
- `resource_service.py`
- `src/config.py`

### 3. 需要重点迁移的领域逻辑

优先级最高的迁移对象：

- `script_subtitle_service.py` -> 功能 7
- `voice_service.py` -> 功能 10 扩展能力层
- `translation_service.py` / `translate` 核心逻辑 -> 功能 11
- 字幕解析与清洗逻辑 -> 功能 7

## 推荐后续动作

在这份 service 映射之后，下一步最自然的是继续整理：

1. 现有代码到新架构的迁移清单
2. 功能域级实施顺序
3. 每个功能域的最小重构切片

## 一句话结论

当前的中间层设计已经可以明确为：

> 现有 `src/app/services` 中的大多数模块应被视为过渡 facade，后续需要按 `1-12` 功能域重组为更清晰的 orchestrator、registry、domain service、artifact service 与 capability service 体系。
