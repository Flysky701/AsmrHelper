# AsmrHelper 第二阶段计划：Legacy Core 替换与主干下沉 V1

## 目标

- 在第一阶段“`core` 主干分区 + task-driven API 收口”基础上，进入真正的 `legacy core` 替换阶段。
- 将当前仍停留在旧技术结构中的核心实现，逐步迁入新的功能域分区。
- 让 `core / service / API` 三层围绕同一套领域对象工作，而不是继续依赖兼容壳层。

## 当前判断

第一阶段已经完成的内容：

- `sessions / tasks / artifacts / runtime / subtitles / engines / orchestration` 的新分区已落地
- `pipeline-runs / tool-runs / tasks / runtime / settings / subtitles / llm` 主接口已基本成形
- 旧 `pipeline / tools / translation / voice` 兼容入口仍可用

当前仍未真正完成的核心问题：

- `PipelineService` 仍通过 `LegacyPipelineOrchestrator` 驱动旧 `src/core/pipeline`
- `PipelineConfig` 仍是旧平铺 provider 参数模型
- `ModelManager` 仍是旧的集中式引擎注册与创建入口
- `src/core/translate/__init__.py` 仍承载大量 LLM 与字幕混合逻辑
- `script_to_subtitle / subtitle_generator / script_processor` 仍未完全归并进 `core/subtitles`

这意味着：

> 第二阶段的重点不是“继续补接口”，而是“把旧核心实现替换为新核心结构”。

## 第二阶段总目标

### 1. 替换旧 pipeline core

- 逐步让 `core/orchestration/pipeline` 不再只是 `LegacyPipelineOrchestrator`
- 建立新的 stage planner / execution context / artifact collection 主路径
- 让 `PipelineService` 最终不再依赖旧 `PipelineConfig`

### 2. 拆解旧 ModelManager

- 将 `llm / asr / tts / separator` 的注册与运行时逻辑进一步分配到各自 `core/engines/*`
- 将 `ModelManager` 降级为兼容入口，而不是主干调度中心

### 3. 收口字幕与文本旧逻辑

- 将 `translate` 包中的字幕加载、清洗、文本处理逻辑迁移到：
  - `core/subtitles`
  - `core/engines/llm`
- 将 `script_to_subtitle` 逐步吸收到新的字幕资产域

### 4. 清理 service 层中的 legacy 依赖

- 让 `PipelineService / AudioToolService / SubtitleService / LlmCapabilityService` 更多依赖新 core，而不是旧大包模块
- 保留兼容路由，但减少兼容 service 内部的旧对象拼装

## 分阶段执行顺序

## Phase 2A：Pipeline 主路径替换

### 范围

- `src/core/orchestration/pipeline/*`
- `src/core/pipeline/*`
- `src/app/services/pipeline_service.py`

### 目标

- 新建真正的 pipeline orchestration 主路径
- 将当前 `LegacyPipelineOrchestrator.build_legacy_config()` 里的逻辑拆成：
  - `stage planner`
  - `execution context builder`
  - `artifact result mapper`
- 让 `PipelineService` 内部减少对旧 `PipelineRequest -> PipelineConfig` 映射的依赖

### 完成标准

- `PipelineService` 仍可兼容旧入口
- 但新任务执行主路径不再需要直接拼完整旧 `PipelineConfig`
- `LegacyPipelineOrchestrator` 降级为兼容适配器

## Phase 2B：ModelManager 拆解

### 范围

- `src/core/model_manager.py`
- `src/core/engines/tts/*`
- `src/core/engines/llm/*`
- `src/core/engines/asr/*`
- `src/core/engines/separator/*`

### 目标

- 将 provider 注册、默认值、运行时创建逻辑按引擎域拆开
- 每个引擎域都拥有自己的最小 registry 能力
- `ModelManager` 只保留兼容查询与兼容构造

### 完成标准

- 新 service 不再优先依赖 `ModelManager`
- `ModelManager` 成为桥接层，不再是新代码默认入口

## Phase 2C：字幕与文本旧逻辑归并

### 范围

- `src/core/translate/__init__.py`
- `src/core/translate/subtitle_cleaner.py`
- `src/core/script_to_subtitle/*`
- `src/core/subtitle_generator.py`
- `src/core/script_processor.py`

### 目标

- 字幕资产逻辑统一进入 `core/subtitles`
- LLM 文本衍生操作统一进入 `core/engines/llm`
- `script_to_subtitle` 从旧独立流程逐步转成字幕领域能力 + LLM 衍生操作组合

### 完成标准

- `SubtitleService` 不再需要从旧 `translate` 包借 subtitle 逻辑
- `llm/operations/run` 可以承接更多文本处理，而不是旁路旧实现

## Phase 2D：兼容层瘦身

### 范围

- `src/app/services/pipeline_service.py`
- `src/app/services/audio_tool_service.py`
- `src/app/services/translation_service.py`
- `src/app/services/tts_service.py`
- `src/app/services/asr_service.py`

### 目标

- 将这些 service 从“旧逻辑总入口”压缩成“新 core 的薄 facade”
- 把更多业务规则下沉到 `core`

### 完成标准

- app services 主要做：
  - 参数校验
  - 调用 core
  - DTO / schema 映射
- 不再大段拼装 legacy 运行模型

## 推荐切片顺序

### 切片 1：PipelineExecutionPlan 下沉

- 在 `core/orchestration/pipeline` 引入显式 execution plan 对象
- 先不替换旧算法，只替换 orchestration 结构

### 切片 2：Engine Registry 拆分

- 在 `tts / llm / asr / separator` 下补 registry
- 将 `ModelManager` 的注册表复制到分域实现

### 切片 3：Subtitle Cleaner 与 Script Processor 归并

- 把 subtitle/text 相关 helper 从 `translate`、`script_processor` 往 `core/subtitles` 收

### 切片 4：Script-to-Subtitle 链路改接新 core

- 让 `ScriptSubtitleService` 尽量走 `core/subtitles + core/engines/llm`

### 切片 5：Legacy facade 瘦身

- 收尾 `pipeline_service / translation_service / tts_service / asr_service`

## 本阶段暂不处理

- 不重做前端页面
- 不重做 GUI worker 全链路
- 不做任务持久化
- 不做分布式或跨进程队列
- 不重做音频算法本身

## 风险点

### 1. 旧 pipeline 算法与新 orchestration 的边界容易反复

- 处理原则：先替换 orchestration，再替换 algorithm adapter

### 2. ModelManager 拆解时可能影响旧 GUI

- 处理原则：保留 `ModelManager` 兼容壳，先让新 service 停止依赖它

### 3. 字幕与 LLM 混合逻辑拆分容易出现重复实现

- 处理原则：先迁 helper，再迁 route/service 调用链，不同时双写

## 阶段完成标准

当下面 5 条满足时，第二阶段可以视为完成：

1. `PipelineService` 新主路径不再依赖完整旧 `PipelineConfig`
2. `ModelManager` 不再是新 service 的主依赖入口
3. `core/subtitles` 成为字幕与脚本文本资产的主归属层
4. `core/engines/llm` 承接主要 LLM 衍生操作
5. app services 明显收薄，主要职责变成 facade

## 一句话结论

第二阶段的目标不是“补更多 endpoint”，而是：

> 将当前已经搭好的新架构外壳，真正替换掉旧 `pipeline / model_manager / translate / script_to_subtitle` 核心主路径。
