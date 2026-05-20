# AsmrHelper 现有代码到新架构的迁移清单 V1

## 目标

- 将当前仓库中的关键代码文件映射到已经确认的新架构功能域。
- 明确每个文件后续应采取的处理方式：
  - 保留
  - 拆分
  - 迁移
  - 兼容保留
  - 最终废弃
- 给出一条可执行的迁移顺序，避免一次性重构过大。

## 使用方式

这份清单不是逐行改造说明，而是“施工图”。

它回答的是：

- 先动哪一批文件最稳
- 哪些文件只是过渡 facade
- 哪些领域逻辑已经放错层，需要迁回正确功能域
- 哪些旧接口和旧页面只保留兼容地位

## 迁移标记说明

### `KEEP`

方向正确，作为新架构基础继续保留。

### `SPLIT`

当前文件职责过大，需要拆成多个新模块。

### `MOVE`

当前能力存在，但应迁移到另一个功能域或 service 层。

### `WRAP`

短期保留为兼容 facade，长期不作为主核心。

### `DEPRECATE`

仅作兼容过渡，后续应弱化或移除。

## 一、配置与资源底座

### `src/config.py`

- 状态：`SPLIT`
- 当前问题：
  - 同时承担读写配置、环境变量覆盖、默认值、简单校验
  - 未来无法承接 `CapabilityDescriptor`、`ExecutionProfile` 的正式管理
- 目标归属：
  - 功能 6：配置与提供方接入管理
- 目标拆分：
  - `SettingsService`
  - `ProviderConfigService`
  - `ConfigOverlayService`

### `src/app/services/resource_service.py`

- 状态：`SPLIT`
- 当前问题：
  - workspace 准备和 runtime readiness 混在一起
- 目标归属：
  - 功能 1：工作空间与输入管理
  - 功能 5：模型与运行资源管理
- 目标拆分：
  - `WorkspaceService`
  - `RuntimeResourceService`

### `src/app/services/model_service.py`

- 状态：`KEEP`
- 当前问题：
  - 还不够完整，但方向正确
- 目标归属：
  - 功能 5：模型与运行资源管理
- 后续动作：
  - 扩展为 `ModelRegistryService`

### `src/core/resources/*`

- 状态：`KEEP`
- 当前问题：
  - 需要从“当前实现集合”提升为运行资源和模型生命周期底层支撑
- 目标归属：
  - 功能 5：模型与运行资源管理

## 二、输入、任务、流水线主干

### `src/app/services/task_service.py`

- 状态：`SPLIT`
- 当前问题：
  - 只是轻量内存状态表
  - 不足以承接统一任务系统
- 目标归属：
  - 功能 3：统一任务生成与任务队列
- 目标拆分：
  - `TaskSpecFactory`
  - `TaskQueueService`
  - `TaskDispatchService`
  - `TaskQueryService`

### `src/app/services/pipeline_service.py`

- 状态：`SPLIT`
- 当前问题：
  - 路径输入、任务创建、执行编排、结果返回混杂
- 目标归属：
  - 功能 2：单任务音频汉化流水线编排执行器
- 目标拆分：
  - `PipelineTaskOrchestrator`
  - `PipelineStepPlanner`
  - `PipelineArtifactService`
  - `PipelineExecutionContextBuilder`

### `src/app/services/batch_pipeline_service.py`

- 状态：`MOVE`
- 当前问题：
  - 当前本质上是循环调用单文件 pipeline
  - 不是真正的任务生成与统一队列
- 目标归属：
  - 功能 3：统一任务生成与任务队列
- 后续动作：
  - 拆成批量任务生成器
  - 不再作为 pipeline 业务本体

### `src/core/pipeline/*`

- 状态：`KEEP`
- 当前问题：
  - 上层接口和职责边界需要重构
- 目标归属：
  - 功能 2：单任务音频汉化流水线编排执行器
  - 功能 8：结果资产与产物索引管理
- 重点迁移：
  - `artifact_collector.py` 要与功能 8 对齐
  - `subtitle_strategy.py` 中字幕逻辑要回归功能 7

## 三、工具体系

### `src/app/services/audio_tool_service.py`

- 状态：`SPLIT`
- 当前问题：
  - 聚合了多种工具能力
  - 容易继续演化成“大杂烩工具 service”
- 目标归属：
  - 功能 4：单步工具执行体系
  - 部分逻辑迁往功能 7 / 8
- 目标拆分：
  - `ToolRegistry`
  - 各工具执行器

### `src/api/http/routes/tools.py`

- 状态：`DEPRECATE`
- 当前问题：
  - 是兼容集合入口，不适合长期主导工具架构
- 目标归属：
  - 功能 4：兼容接口层
- 后续动作：
  - 长期让 `tool-runs` 成为主入口

### `desktop/src/pages/tools/Tools.tsx`

- 状态：`DEPRECATE`
- 当前问题：
  - 当前页面在本地维护任务视图和工具入口逻辑
- 目标归属：
  - 前端消费层
- 后续动作：
  - 不再主导工具能力边界
  - 改为消费功能 3 和功能 4 的标准接口

## 四、字幕与脚本文本

### `src/app/services/subtitle_service.py`

- 状态：`KEEP`
- 当前问题：
  - 还不足以覆盖完整字幕领域，但方向正确
- 目标归属：
  - 功能 7：字幕与文本资产管理
- 后续动作：
  - 扩展为 `SubtitleAssetService` / `SubtitleParserService` 等

### `src/app/services/script_subtitle_service.py`

- 状态：`MOVE`
- 当前问题：
  - 当前同时承担应用入口和领域语义
- 目标归属：
  - 功能 7：字幕与文本资产管理
- 后续动作：
  - 应用 facade 可以短期保留
  - 领域逻辑下沉到 `ScriptSubtitleDomainService`

### `src/core/subtitle_generator.py`

- 状态：`MOVE`
- 当前问题：
  - 导出能力还只是底层工具
- 目标归属：
  - 功能 7：字幕与文本资产管理
  - 功能 8：结果资产与产物索引管理

### `src/core/script_to_subtitle/*`

- 状态：`MOVE`
- 当前问题：
  - 其中混合了脚本处理、LLM 清洗、ASR 结果消费、字幕导出
- 目标归属：
  - 功能 7：脚本转字幕领域逻辑
  - 功能 11：其中 LLM 清洗 / 对齐逻辑
  - 功能 12：其中 ASR 结果消费部分

### `src/core/translate/subtitle_cleaner.py`

- 状态：`MOVE`
- 当前问题：
  - 逻辑位置不对
- 目标归属：
  - 功能 7：字幕与文本资产管理

## 五、TTS、LLM、ASR 能力域

### `src/app/services/tts_service.py`

- 状态：`WRAP`
- 当前问题：
  - 当前是单一 TTS facade，无法表达未来多引擎结构
- 目标归属：
  - 功能 10：TTS 引擎管理与扩展能力管理
- 后续动作：
  - 保留为兼容 facade
  - 底层能力迁向 `TtsEngineExecutionService`

### `src/app/services/voice_service.py`

- 状态：`MOVE`
- 当前问题：
  - 容易被误认成一级主功能域
- 目标归属：
  - 功能 10：TTS 引擎扩展能力层
- 后续动作：
  - 重命名语义为 `VoiceExtensionService`
  - 不再主导产品级边界

### `src/core/tts/*`

- 状态：`KEEP`
- 当前问题：
  - 需要从“当前实现集合”提升为 TTS 引擎与扩展能力底层实现
- 目标归属：
  - 功能 10：TTS 引擎管理与扩展能力管理

### `src/app/services/translation_service.py`

- 状态：`WRAP`
- 当前问题：
  - 当前命名仍像独立翻译引擎入口
- 目标归属：
  - 功能 11：LLM 能力管理与衍生操作管理
- 后续动作：
  - 保留兼容 facade
  - 长期语义降级为 LLM 衍生操作入口

### `src/core/translate/*`

- 状态：`SPLIT`
- 当前问题：
  - 同时混有：
    - LLM 翻译逻辑
    - 字幕解析
    - 字幕清洗
    - 术语与质量检查
- 目标归属：
  - 功能 11：LLM 衍生操作
  - 功能 7：字幕领域逻辑
- 后续动作：
  - 拆出纯 LLM 调用与翻译能力
  - 将字幕领域逻辑迁回功能 7

### `src/core/script_to_subtitle/llm_processor.py`

- 状态：`MOVE`
- 当前问题：
  - 现在只是脚本转字幕内部实现细节
- 目标归属：
  - 功能 11：LLM 衍生操作管理
- 后续动作：
  - 提升为通用 LLM 文本清洗 / 对齐能力之一

### `src/app/services/asr_service.py`

- 状态：`WRAP`
- 当前问题：
  - 当前是单一 ASR facade，无法表达未来多引擎结构
- 目标归属：
  - 功能 12：ASR 引擎管理与扩展能力管理
- 后续动作：
  - 保留兼容 facade
  - 底层能力迁向 `AsrEngineExecutionService`

### `src/core/asr/*`

- 状态：`KEEP`
- 当前问题：
  - 当前主要体现单引擎实现
- 目标归属：
  - 功能 12：ASR 引擎管理与扩展能力管理
- 后续动作：
  - 抽出 registry / capability / adapter 结构

## 六、结果资产与预览

### `src/core/pipeline/artifact_collector.py`

- 状态：`MOVE`
- 当前问题：
  - 目前还只是 pipeline 私有收集器雏形
- 目标归属：
  - 功能 8：结果资产与产物索引管理

### `desktop` 结果展示与播放器骨架

- 状态：`WRAP`
- 当前问题：
  - 页面逻辑不应反向主导结果模型
- 目标归属：
  - 功能 9：结果预览、浏览与人工校对
- 后续动作：
  - 先接入轻量预览方案

## 七、HTTP 路由层迁移

### 建议长期保留为主接口的 route

- `tasks.py`
- `subtitles.py`
- `models.py`
- `resources.py`
- 未来统一后的 `tool-runs`
- 未来统一后的 `llm/*`
- 未来增强后的 `tts/*`
- 未来增强后的 `asr/*`

### 建议保留为兼容层的 route

- `translation.py`
- `voice.py`
- `tools.py`
- 当前平铺字段风格的 `pipeline.py`

## 八、推荐迁移顺序

### 阶段 1：先收口主干契约

优先处理：

- `src/config.py`
- `resource_service.py`
- `task_service.py`
- `pipeline_service.py`

目标：

- 先让配置、资源、任务、单任务编排的主契约稳定下来

### 阶段 2：收口字幕与结果资产

优先处理：

- `subtitle_service.py`
- `script_subtitle_service.py`
- `src/core/subtitle_generator.py`
- `src/core/script_to_subtitle/*`
- `src/core/pipeline/artifact_collector.py`

目标：

- 先让字幕与结果资产成为稳定中间层

### 阶段 3：收口工具和兼容 facade

优先处理：

- `audio_tool_service.py`
- `asr_service.py`
- `tts_service.py`
- `translation_service.py`

目标：

- 把这些从“中心业务层”降到“工具执行器 / 兼容 facade”

### 阶段 4：收口引擎能力域

优先处理：

- `src/core/tts/*`
- `src/core/asr/*`
- `src/core/translate/*`
- `voice_service.py`

目标：

- 真正建立 TTS / LLM / ASR 的 provider / engine 能力域

### 阶段 5：收口前端消费层

优先处理：

- `Tools.tsx`
- `VoiceLab.tsx`
- `Settings.tsx`
- 结果预览 UI

目标：

- 让前端彻底改为消费标准接口，而不是继续定义能力边界

## 九、当前阶段最不该做的事

为避免再次被历史实现拖住，当前最不建议直接做：

- 先改页面再倒推后端
- 在旧 `PipelineService` 里继续叠加逻辑
- 在 `audio_tool_service.py` 里再加更多工具分支
- 把 `voice_service.py` 继续当成一级主功能中心
- 把 `translation_service.py` 继续当成独立引擎层

## 一句话结论

当前仓库的迁移方向已经可以明确为：

> 先把现有大而混的应用层 facade 拆成稳定主干、字幕资产层、结果资产层和引擎能力域，再让页面和旧 route 逐步退回到兼容与消费角色。
