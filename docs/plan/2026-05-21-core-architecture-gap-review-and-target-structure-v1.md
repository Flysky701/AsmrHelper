# AsmrHelper Core 架构差异复核与目标结构 V1

## 目标

- 明确当前 `src/core` 与既定功能文档之间的真实差异。
- 判断当前阶段到底完成了什么，哪些还停留在过渡层。
- 给出一版可落地的 `core` 目标目录结构，作为下一轮后端重构基线。

## 结论先行

当前仓库已经完成的是：

- 一轮 **应用层适配与 API 收口**
- 一部分 **任务驱动入口**
- 一部分 **结果索引与能力注册表雏形**

当前仓库还没有完成的是：

- 按功能域重建 `src/core`
- 把功能文档中的主干边界真正落实到后端核心层
- 让 API、service、core 三层围绕同一套对象模型运转

更准确地说，当前状态不是“后端设计已完成”，而是：

> 文档架构已完成，应用层已有过渡壳层，但 `core` 仍主要停留在旧技术实现结构，尚未按功能域重构。

## 当前 `src/core` 现实结构

当前 `src/core` 主要由下面这些旧实现模块组成：

- `asr`
- `pipeline`
- `resources`
- `script_to_subtitle`
- `translate`
- `tts`
- `vocal_separator`
- `gpu_manager.py`
- `model_manager.py`
- `script_processor.py`
- `subtitle_generator.py`

当前 `src/core/__init__.py` 仍然直接导出：

- `VocalSeparator`
- `ASRRecognizer`
- `Translator`
- `TTSEngine`
- `Pipeline`
- `PipelineConfig`
- `ModelManager`
- `ModelService`

这说明当前 `core` 的组织方式仍然是：

- 按技术实现分区
- 按当前类库和当前 provider 分区
- 按旧流程入口暴露能力

而不是按已经确认的功能域分区。

## 与功能文档的主要差异

### 1. 功能 1 / 3 在 `core` 中基本缺位

文档主干要求系统围绕：

- 输入与会话
- 任务系统
- 资产模型
- 结果索引
- 配置与运行条件

但当前 `core` 中没有独立的：

- `session`
- `task`
- `queue`
- `artifact index`
- `preview`

这些能力目前主要落在：

- `src/app/services`
- `src/app/dto`

这意味着：

- 功能 1 和功能 3 还没有进入核心后端层
- 当前只是应用层先把这些对象补出来了

### 2. 功能 7 与功能 11 在 `core` 中仍然混杂

文档要求：

- 功能 7：字幕与文本资产管理
- 功能 11：LLM 能力管理与衍生操作管理

但当前实际情况是：

- `src/core/translate/__init__.py` 同时承担
  - LLM 调用
  - 字幕格式识别
  - 字幕时间轴加载
  - 字幕清洗入口
- `src/core/script_to_subtitle/*` 又单独保留了一套脚本转字幕流程
- `src/core/subtitle_generator.py` 继续承载字幕生成与对齐逻辑
- `src/core/script_processor.py` 继续承载脚本清洗与文本抽取逻辑

这导致字幕与文本相关逻辑仍然散落在：

- `translate`
- `script_to_subtitle`
- `subtitle_generator.py`
- `script_processor.py`

所以功能 7 并没有成为字幕业务唯一归属层。

### 3. 功能 2 仍然绑定旧 `PipelineConfig`

文档要求功能 2 是：

- 单任务音频汉化流水线编排执行器
- 消费功能 10 / 11 / 12 的引擎能力域
- 消费功能 7 / 8 的资产能力

但当前 `src/core/pipeline/__init__.py` 里的 `PipelineConfig` 仍直接暴露：

- `translate_provider`
- `translate_model`
- `tts_engine`
- `tts_voice`
- `qwen3_voice`
- `voice_profile_id`
- `asr_model`
- `vocal_model`

这说明：

- 新的 `CapabilityDescriptor / ExecutionProfile / RuntimeBinding` 没有进入 core pipeline
- pipeline 仍然直接知道 provider 私有语义
- pipeline 仍然是旧平铺参数模型

### 4. 功能 10 / 11 / 12 仍然被 `ModelManager` 集中硬编码

文档要求：

- TTS、LLM、ASR 是三个独立引擎能力域
- 各自应具备 registry / execution / extension capability 的演进空间

但当前 `src/core/model_manager.py` 仍然是单文件统一管理：

- `llm`
- `asr`
- `tts`
- `separator`

问题在于：

- registry 在一个文件里硬编码
- provider 默认值直接从 `config` 读取
- 引擎私有能力没有独立扩展边界
- 没有独立的 TTS / LLM / ASR core capability layer

这意味着功能 10 / 11 / 12 在 core 层还没有真正分家。

### 5. 功能 5 只完成了一半

当前 `src/core/resources` 已经有：

- `model_catalog.py`
- `model_installer.py`
- `model_status.py`
- `model_service.py`

这说明“模型资产管理”有一定基础。

但缺失仍然很明显：

- 没有独立 runtime resource core
- 没有 task readiness 规则核心层
- 没有统一 runtime binding 解析层

所以功能 5 目前更像“模型管理已成形，运行资源管理未成形”。

### 6. 功能 8 / 9 尚未进入 `core`

当前：

- `artifact` 相关索引主要在 `src/app/services/artifact_service.py`
- `review` 状态主要在 `src/app/services/task_service.py`

这意味着：

- 功能 8 还没有 core artifact model / index 层
- 功能 9 也还没有 core preview / review model 层

## 当前状态应如何重新定性

### 已完成

- 功能文档架构定义
- API 主方向定义
- service 层第一轮适配
- 一批 task-driven route
- 一批过渡 facade

### 未完成

- `core` 按功能域重构
- `core` 与 service 的边界统一
- `core` 与 API 契约统一
- provider / engine 能力域真正下沉到核心层

### 当前阶段正确名称

建议把当前状态正式定性为：

> **过渡层完成阶段**

而不是：

> **后端设计完成阶段**

## 目标 `core` 结构建议

下面这版不是要求一轮全部实现，而是作为下一轮 core 重构目标结构。

### A. 主干层

建议新增：

- `src/core/sessions/`
- `src/core/tasks/`
- `src/core/artifacts/`
- `src/core/runtime/`

#### `src/core/sessions/`

建议承载：

- `WorkspaceContext`
- `InputAsset`
- `ProcessingSession`
- companion discovery policy
- output policy resolver

#### `src/core/tasks/`

建议承载：

- `TaskSpec`
- `TaskRecord`
- task state machine
- queue policy
- retry / cancel / skip rule

#### `src/core/artifacts/`

建议承载：

- `Artifact`
- `ArtifactSet`
- primary artifact policy
- artifact indexing rule
- preview kind rule

#### `src/core/runtime/`

建议承载：

- runtime resource discovery
- task readiness rule
- runtime binding resolver
- environment / dependency capability probe

### B. 字幕与文本资产层

建议新增：

- `src/core/subtitles/`

建议承载：

- subtitle document model
- parser
- normalize
- bilingual assembly
- export
- script subtitle domain rule

建议把下面这些旧实现逐步迁入：

- `subtitle_generator.py`
- `script_processor.py`
- `script_to_subtitle/*`
- `translate` 中的 subtitle loader / cleaner 逻辑

### C. 引擎能力域层

建议新增：

- `src/core/engines/tts/`
- `src/core/engines/llm/`
- `src/core/engines/asr/`
- `src/core/engines/separator/`

#### `src/core/engines/tts/`

建议承载：

- engine registry
- synthesize execution
- profile / clone / preview extension capability

旧实现迁移来源：

- `tts/*`
- `voice_service` 对应能力未来下沉点

#### `src/core/engines/llm/`

建议承载：

- provider registry
- llm execute client
- derived operations
  - translation
  - script cleaning
  - alignment
  - rewrite

旧实现迁移来源：

- `translate/__init__.py` 中的 `Translator`
- `script_to_subtitle/llm_processor.py`

#### `src/core/engines/asr/`

建议承载：

- engine registry
- recognize execution
- result adapter
- extension capabilities
  - vad
  - prompt
  - word timestamps
  - diarization

旧实现迁移来源：

- `asr/*`

#### `src/core/engines/separator/`

建议承载：

- separator registry
- separation execution

旧实现迁移来源：

- `vocal_separator/*`

### D. 编排层

建议新增：

- `src/core/orchestration/pipeline/`
- `src/core/orchestration/tools/`

#### `src/core/orchestration/pipeline/`

建议承载：

- stage planner
- execution context builder
- pipeline orchestration rule

旧实现迁移来源：

- `core/pipeline/*`

#### `src/core/orchestration/tools/`

建议承载：

- tool task mapping
- tool execution contract

## 旧 `core` 模块的迁移建议

### 建议拆分迁移

- `src/core/translate/__init__.py`
  - 拆到 `core/engines/llm` 和 `core/subtitles`
- `src/core/model_manager.py`
  - 拆到 `core/engines/*` registry 层
- `src/core/pipeline/__init__.py`
  - 拆到 `core/orchestration/pipeline`
- `src/core/subtitle_generator.py`
  - 迁到 `core/subtitles`
- `src/core/script_processor.py`
  - 迁到 `core/subtitles`

### 建议保留但重挂路径

- `src/core/asr/*`
- `src/core/tts/*`
- `src/core/resources/*`
- `src/core/vocal_separator/*`

这些能力本体并不是不能用，而是路径和职责需要重挂。

### 建议最终降级为兼容层

- `src/core/__init__.py`
- 旧 `PipelineConfig`
- 旧 `ModelManager`
- 旧 `Translator`

原因不是它们“错误”，而是它们继续作为主入口会持续把系统拉回旧边界。

## 推荐重构顺序

### Phase A：先重建主干 core

优先新增：

- `core/sessions`
- `core/tasks`
- `core/artifacts`
- `core/runtime`

这是后续所有层的共同依赖。

### Phase B：再收口字幕与文本

优先新增：

- `core/subtitles`

并迁走：

- `subtitle_generator.py`
- `script_processor.py`
- `script_to_subtitle/*`
- `translate` 中 subtitle 相关逻辑

### Phase C：再拆引擎能力域

优先新增：

- `core/engines/tts`
- `core/engines/llm`
- `core/engines/asr`

这一阶段处理 `ModelManager` 的拆分。

### Phase D：最后重构编排层

优先新增：

- `core/orchestration/pipeline`
- `core/orchestration/tools`

这一阶段再回头改 `PipelineService`、`ToolRegistry` 的下游依赖方向。

## 本轮复核结论

可以明确给出三个判断：

1. **设计文档与当前 core 代码没有对上**
2. **当前仓库还没有完成按功能域组织的后端核心层**
3. **当前已经完成的是应用层过渡封装，不是 core 重构完成**

## 一句话结论

当前 AsmrHelper 的真正缺口不是“再补几个 route”，而是：

> 需要把已经完成的功能架构文档，真正下沉成 `src/core` 的功能域分区，否则 service 和 API 只能继续停留在过渡层。
