# AsmrHelper 总体进度状态更新 V1

## 目标

- 以当前仓库实际状态为准，形成一份新的阶段性总盘点。
- 统一说明后端重构、桌面端集成、文档状态和下一步主线。
- 替代已经过时的阶段里程碑快照，避免继续参考旧状态。

## 当前仓库状态

- 当前分支：`refactor/re-design`
- 与远端关系：本地领先 `origin/refactor/re-design` 4 个提交
- 当前工作区：**不是干净状态**

当前未提交变动集中在文档整理：

- 修改 `.gitignore`
- 归档旧文档 `docs/plan/2026-05-21-phase2-milestone-status-v1.md`
- 新增本状态文档 `docs/plan/2026-05-21-overall-progress-status-update-v1.md`

也就是说：

> 代码主干当前是稳定的，工作区不干净主要来自“状态文档更新 + 文档归档动作”，不是新的代码层不确定改动。

## 当前可验证状态

- `python -m compileall src` 可通过
- `create_app()` 可启动
- 当前 API 路由数：`94`

说明：

- 后端主干是可启动、可导入、可继续推进的
- 当前不是“恢复阶段”，而是“持续重构阶段”

## 架构状态总判断

当前项目已经完成的部分：

1. 功能 `1-12` 的架构边界定义
2. 第一阶段 `core` 主干分区和 task-driven API 收口
3. 第二阶段的第一轮 `legacy core` 替换
4. 桌面端六大页面与后端主接口的第一轮接线

当前仍未完成的部分：

1. `legacy pipeline core` 的彻底退场
2. `ModelManager` 的完全兼容层化
3. 字幕与文本旧逻辑的最终归并
4. app facade 的系统性瘦身
5. 桌面端对新任务主线和新能力域的进一步对齐

因此，当前正确状态应定义为：

> 功能架构已经完成，第一阶段已经完成，第二阶段正在推进中，桌面端第一轮集成也已经完成，但后端核心替换尚未收官。

## 功能域进度

### 功能 1：工作空间与输入管理

状态：`基本落地`

已完成：

- `workspaces / inputs / sessions`
- `WorkspaceService / InputCatalogService / SessionService`
- 输入资产、伴随资源发现、输出策略、会话创建主线

剩余：

- 无明显结构性阻塞项

### 功能 2：单任务音频汉化流水线编排执行器

状态：`进行中，主干已切开`

已完成：

- `pipeline-runs`
- task-driven 执行路径
- `PipelineExecutionPlan`
- orchestration 结果归一
- step executor 优先走新 `engines runtime`

剩余：

- 仍未完全摆脱旧 `src/core/pipeline`
- `LegacyPipelineOrchestrator` 仍未彻底退为适配层

这是当前最大的核心未完成项。

### 功能 3：统一任务生成与任务队列

状态：`基本落地`

已完成：

- `tasks / tasks/batch / retry / task-queue`
- `TaskSpec / TaskStatus / TaskQueueSnapshot`
- pipeline 和 tool 任务统一进入任务系统

剩余：

- 当前是轻量实现，不是复杂持久化调度系统

### 功能 4：单步工具执行体系

状态：`已接入主干，仍可继续瘦身`

已完成：

- `tool-runs`
- 工具任务统一进入功能 3
- `AudioToolService` 已开始消费新字幕域和新 LLM runtime

剩余：

- 仍有部分旧 facade 逻辑没有完全收净

### 功能 5：模型与运行资源管理

状态：`大体落地`

已完成：

- `runtime/resources`
- `runtime/capabilities`
- `runtime/check-task-readiness`
- 模型状态与运行前检查主线

剩余：

- GUI 和少量兼容路径未完全脱离旧模型管理方式

### 功能 6：配置与提供方接入管理

状态：`基本落地`

已完成：

- `settings / effective / validate / test-provider / capabilities`
- `CapabilityDescriptor / ExecutionProfile / RuntimeBinding`
- provider 参数分层和默认值逻辑

剩余：

- 继续服务于后续 provider 整理，无单独大阻塞

### 功能 7：字幕与文本资产管理

状态：`已成形，仍在继续归并 legacy`

已完成：

- `subtitles/parse / normalize / translate / bilingualize / export / script-to-subtitle`
- 新 `core/subtitles`
- loader / exporter / bilingualize 主线

已推进到：

- 部分应用层翻译入口已改走 `LlmOperationRuntime`

剩余：

- `translate / script_to_subtitle / subtitle_generator / script_processor` 里仍有旧逻辑待完全归并

### 功能 8：结果资产与产物索引管理

状态：`轻量可用`

已完成：

- artifact 索引
- `by-task` 查询
- artifact detail / file
- pipeline / tool / subtitle 产物挂接

剩余：

- 当前足够支撑主线，但不是重型资产系统

### 功能 9：结果预览、浏览与人工校对

状态：`轻量方案已落地`

已完成：

- `preview`
- `review-status`
- `review-note`

范围说明：

- 当前就是已确认的轻量版本
- 不包含 cue 级编辑、多人协作审校、复杂返工流

### 功能 10：TTS 引擎管理与扩展能力管理

状态：`主干已落地，扩展能力仍在过渡`

已完成：

- `tts/engines`
- `TtsRegistry`
- `TtsEngineRuntime`

剩余：

- 旧 `tts` 包和部分 Qwen3 扩展逻辑未完全归整进新能力域

### 功能 11：LLM 能力管理与衍生操作管理

状态：`主干已落地，继续收口中`

已完成：

- `llm/providers`
- `llm/operations/run`
- 当前支持：
  - `translate`
  - `clean_script`
  - `rewrite_text`

已推进到：

- `subtitle_service`
- `audio_tool_service`
- `script_to_subtitle` 部分路径

开始统一消费 `LlmOperationRuntime`

剩余：

- 旧 `translate` 包里的剩余文本/字幕逻辑仍要继续归并

### 功能 12：ASR 引擎管理与扩展能力管理

状态：`主干已落地`

已完成：

- `asr/engines`
- `AsrRegistry`
- `AsrEngineRuntime`

剩余：

- 主要作为 `Phase 2A/2B` 的被消费能力域继续稳定化

## 阶段进度

### Phase 1：主干分区 + task-driven API 收口

状态：`已完成`

已完成内容：

- `core` 新主干分区建立
- task-driven API 主线建立
- 轻量 preview/review 和 artifact 主路径建立

### Phase 2：Legacy Core 替换

状态：`进行中`

#### Phase 2A：Pipeline 主路径替换

状态：`进行中，已切开主干`

已完成：

- `ExecutionPlan`
- `forced_active_steps`
- orchestration 结果归一
- step executor 优先走新 `engines runtime`
- `primary_output` 等结果语义开始统一

剩余：

- 彻底摆脱旧 `core.pipeline` 主执行逻辑
- 继续把 step 结果结构和阶段元数据收向 orchestration

#### Phase 2B：ModelManager 拆解

状态：`进行中`

已完成：

- `tts / llm / asr / separator` registry 已建立
- 多处运行时入口已优先走 registry
- unload 兼容语义已修正

剩余：

- `ModelManager` 明确退为兼容层
- GUI / 旧路径对它的剩余依赖清理

#### Phase 2C：字幕与文本旧逻辑归并

状态：`进行中`

已完成：

- 新 `core/subtitles`
- loader / exporter / bilingualize
- 部分应用层翻译入口切到新 LLM runtime

剩余：

- `translate / script_to_subtitle / subtitle_generator / script_processor` 的剩余归并

#### Phase 2D：兼容层瘦身

状态：`未正式收尾`

当前判断：

- `pipeline_service / audio_tool_service / translation_service / tts_service / asr_service`
  已经比最初更薄
- 但还未达到“纯 facade”状态

## 桌面端进度

状态：`第一轮集成已完成`

从最近提交看，桌面端已经完成：

- 导航重构为新的六大主页面
- 各 tab 页面和后端主接口的第一轮接线
- `Workbench / TaskCenter / EnginesResources / Settings / VoiceLab` 等页面框架已经在位

当前判断：

- 桌面端已经不是空壳
- 但它仍然建立在“后端第二阶段尚未完全收官”的基础上
- 后续还需要继续跟随新任务主线和新能力域做对齐

## 当前最重要的剩余问题

1. `pipeline` 底层仍未完全摆脱旧 `src/core/pipeline`
2. `ModelManager` 仍未完全退居兼容层
3. 旧字幕/文本逻辑仍有部分散落在 legacy 路径
4. app service 仍需继续系统性瘦身
5. 桌面端还需要继续对齐新的后端主路径

## 推荐下一步

### 优先级 1：继续推进 Phase 2A

- 继续收 `src/core/pipeline/step_executor.py`
- 继续把 step 结果语义、阶段元数据、artifact/result 组装往 `core/orchestration/pipeline` 收

### 优先级 2：继续推进 Phase 2C

- 把 `script_to_subtitle`
- `subtitle_generator`
- `script_processor`
- `translate` 包中的剩余字幕/文本逻辑继续归并

### 优先级 3：推进 Phase 2B 收尾

- 让 `ModelManager` 更明确退为兼容层
- 清理剩余 runtime-facing 依赖

### 优先级 4：最后做 Phase 2D

- 系统性瘦身 app facade
- 收尾 `pipeline_service / audio_tool_service / translation_service / tts_service / asr_service`

## 一句话结论

当前项目已经完成第一阶段，并进入第二阶段的主路径替换期：

> 架构、API 主线、core 新分区和桌面端第一轮集成都已经建立完成，当前工作的核心不再是“定义功能”，而是继续替换 `legacy pipeline / ModelManager / translate / script_to_subtitle` 这些旧核心主路径。
