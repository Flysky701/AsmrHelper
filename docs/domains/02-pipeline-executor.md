# 功能 2：单任务音频汉化流水线编排执行器 V1 计划

## 目标

- 将“完整音频汉化流水线”重新定义为单任务编排执行器，而不是批处理入口、任务系统入口或页面动作集合。
- 明确该模块只负责编排并执行一个 `pipeline` 类型任务，不再负责拆文件、排队、调度或多任务编排。
- 为后续统一任务系统提供一个清晰的执行器边界，使其能够作为功能 3 的任务消费者接入。

## 背景

- 当前仓库中的 `PipelineService` 同时承担了路径输入接收、任务创建、步骤控制、阶段执行、结果返回等多重职责。
- 当前 `/api/v1/pipeline/run` 直接接收 `input_path`、`output_dir` 和一组执行参数，仍然是“路径驱动”的调用方式。
- 当前 `BatchPipelineService` 通过循环调用单文件 pipeline 实现批处理，这意味着“单任务编排执行器”和“批量任务编排器”尚未被拆开。
- 经边界确认后，系统需要将 pipeline 重新收敛为“单任务编排执行器”，并把任务生成、排队和调度上移到功能 3。

## 功能定位

该功能域负责编排并执行一个已经定义好的 `pipeline` 任务。

它的核心职责是：

1. 读取任务上下文。
2. 装载任务关联的输入会话。
3. 解析本次运行的阶段计划。
4. 编排并执行音频汉化的各处理阶段。
5. 收集产物。
6. 回写任务结果、阶段结果与错误语义。

阶段进度、运行日志、警告和错误事件的统一表示以 [基础设施契约 V1](../contracts/infrastructure-contracts-v1.md) 中的 `RuntimeEvent` 为准。

它不负责决定要执行多少个任务，也不负责多个任务的排队顺序。

## 边界

### 本功能负责

- 编排并执行单个 `pipeline` 类型任务。
- 根据任务参数决定本次运行的步骤计划。
- 调用人声分离、ASR、翻译、TTS、混音、字幕导出等底层能力。
- 记录单任务内部的阶段状态。
- 生成结构化的产物清单。
- 生成单任务级别的 warnings / error message / duration。

### 本功能不负责

- 不负责文件选择、输入识别、输出目录规划，这些由功能 1 负责。
- 不负责批量拆任务、共享参数复制、队列入队、优先级调度，这些由功能 3 负责。
- 不负责小工具任务执行，这些属于功能 4。
- 不负责字幕领域模型、字幕解析、双语字幕组装与字幕导出规则定义，这些属于功能 7。
- 不负责模型安装、资源准备、设置持久化。
- 不负责前端页面的任务列表、日志面板、交互样式。

## V1 需要实现的功能

### 1. 单任务上下文装载

编排执行器需要以任务对象为入口，而不是直接以裸路径为入口。

V1 任务对象至少应提供：

- `task_id`
- `task_type`
- `session_id`
- `input_asset_id`
- `companion_asset_ids`
- `run_options`

编排执行器需要通过 `session_id` 装载：

- 主音频输入
- 已确认的伴随字幕或脚本
- 已解析好的输出目录
- 临时目录

### 2. 运行参数解析

V1 不再将流水线参数定义为一组平铺字段，而是要求任务携带已经冻结的 `ExecutionProfile`。

`ExecutionProfile` 的职责是表达“这次任务实际要怎么跑”，但不携带敏感凭据和运行时资源。

V1 至少需要按阶段拆分以下配置：

- `asr_profile`
- `translation_profile`
- `tts_profile`
- `mix_profile`

每个 profile 至少应包含：

- `category`
- `provider`
- `model`
- `common_options`
- `provider_options`

示例：

```json
{
  "tts_profile": {
    "category": "tts",
    "provider": "qwen3_tts",
    "model": "default",
    "common_options": {
      "voice": "custom_01",
      "speed": 1.0
    },
    "provider_options": {
      "voice_profile_id": "vp_001",
      "emotion": "soft"
    }
  }
}
```

V1 不再把“preset 名称”作为核心产品契约，而是将其视为可选模板来源。编排执行器最终消费的必须是标准化后的阶段 profile。

### 2.1 运行时绑定

编排执行器在真正执行前，还需要从功能 5 与功能 6 获取 `RuntimeBinding`。

`RuntimeBinding` 的职责是表达“这次运行真正注入了哪些运行时资源”，例如：

- API key
- base URL
- 本地模型路径
- device
- provider runtime client

`RuntimeBinding` 不写入任务，不进入队列快照，只在执行时注入。

### 3. 阶段计划生成

编排执行器需要在实际运行前生成标准阶段计划。

V1 建议明确以下标准阶段：

1. `separation`
2. `asr`
3. `translation`
4. `tts`
5. `mix`
6. `subtitle_export`

每个阶段都需要拥有独立状态，而不是只在最终返回一个成功或失败。

V1 阶段状态建议为：

- `pending`
- `running`
- `skipped`
- `completed`
- `failed`

### 4. 单任务执行

编排执行器需要按阶段计划逐步运行。

V1 处理链建议如下：

1. 从主音频开始。
2. 视配置执行人声分离。
3. 对目标音轨执行 ASR。
4. 对文本执行翻译。
5. 对翻译文本执行 TTS。
6. 对原音轨与 TTS 音轨执行混音。
7. 输出字幕文件。
8. 汇总所有结果。

V1 允许：

- 因显式配置或上下文条件跳过某些阶段。
- 在已有伴随字幕的情况下跳过部分步骤。

V1 不允许：

- 由页面逻辑在调用前隐式决定步骤顺序。
- 由执行器私自修改输入会话。

### 5. 产物收集

编排执行器需要返回结构化产物，而不是只返回一个 `mix_path`。

V1 至少需要收集：

- `primary_output`
- `mix`
- `subtitle`
- `tts_audio`
- `vocals`
- `transcript`

V1 允许缺失某些中间产物，但缺失需要有明确语义：

- 因步骤跳过而不存在
- 因执行失败而不存在

### 6. 单任务结果回写

编排执行器需要将执行结果写回任务系统，而不再自行扮演任务系统。

V1 单任务结果至少需要包含：

- `task_id`
- `status`
- `step_results`
- `artifacts`
- `warnings`
- `error_message`
- `duration_seconds`

## 对外 API 设计

V1 建议采用“单任务编排执行器视角”的 API，而不是批处理入口。

### `POST /api/v1/pipeline-runs`

用途：

- 触发一个 `pipeline` 类型任务执行

请求体示例：

```json
{
  "task_id": "task_pipeline_001"
}
```

如果系统在 V1 仍需保留创建即执行的形式，则请求体也可临时允许：

```json
{
  "session_id": "sess_xxx",
  "run_options": {
    "source_lang": "ja",
    "target_lang": "zh",
    "use_vocal_separator": true,
    "asr_model": "base",
    "translate_provider": "deepseek",
    "tts_engine": "edge",
    "tts_voice": "zh-CN-XiaoxiaoNeural",
    "original_volume": 0.85,
    "tts_volume_ratio": 0.5,
    "tts_delay": 0.0,
    "skip_existing": false
  }
}
```

但长期目标仍应以 `task_id` 启动执行为准。

### `GET /api/v1/pipeline-runs/{task_id}`

用途：

- 查询单个 `pipeline` 任务的执行状态与结构化结果

响应体至少应包含：

- `task_id`
- `status`
- `step_results`
- `artifacts`
- `warnings`
- `error_message`
- `duration_seconds`

### `GET /api/v1/pipeline-runs/{task_id}/artifacts`

用途：

- 单独获取产物清单，便于前端直接绑定结果视图

### `POST /api/v1/pipeline-runs/{task_id}/cancel`

用途：

- 取消当前执行中的单任务 pipeline

V1 可以先只保留设计，不要求同轮实现。

## 中间层设计

### `PipelineTaskOrchestrator`

职责：

- 读取 `pipeline` 任务
- 装载 `session`
- 读取 `ExecutionProfile`
- 在执行前请求 `RuntimeBinding`
- 编排完整处理链
- 回写单任务结果

不负责：

- 创建任务
- 批量拆分
- 队列调度

### `PipelineStepPlanner`

职责：

- 根据 `ExecutionProfile` 与输入上下文生成标准阶段计划
- 决定哪些阶段执行，哪些阶段跳过

不负责：

- 真正的阶段执行
- 结果存储

### `PipelineArtifactService`

职责：

- 收集主产物与中间产物
- 统一产物命名与对外结构
- 输出 `ArtifactSet` 或等价结果

不负责：

- 生成业务参数
- 管理任务状态机

## 与当前实现的关系

### 当前实现状态

- 当前 `src/core/pipeline/` 已从源码树移除。
- pipeline 主路径已经迁到 `src/core/orchestration/pipeline/`。
- `PipelineExecutor` 已直接消费 separator / ASR / LLM / TTS / mixer runtime。
- 当前剩余问题不是“继续替换旧 pipeline 包”，而是让 execution profile、任务状态、artifact/preview 语义与主链路契约完全对齐。

### 必须重写或重组的部分

- `PipelineRequest(input_path, output_dir, ...)` 兼容入口需要从路径驱动逐步迁移为 `session + task`。
- `src/app/services/pipeline_service.py` 当前仍承担兼容请求适配、任务 spec 创建、执行调用和 artifact 注册，需要继续压薄。
- 当前 `/api/v1/pipeline/run` 的输入契约过于贴近历史实现。
- 当前 `PipelineService.create_pipeline_task_spec()` 生成的 execution profile 仍偏旧结构，需要对齐 [主链路 V1 数据参数契约](../contracts/mainline-v1-data-parameters.md)。
- 当前 `TaskStatus` 还缺少显式 `stage / error / timestamps / artifact_set_id`，需要补齐后再让 TaskCenter 消费。

### 明确不继承的历史包袱

- 不继承“pipeline 自己创建 task”的方式。
- 不继承“preset 名称就是能力定义”的方式。
- 不继承“返回一个主路径就算任务结果”的方式。
- 不继承“批处理只是循环调用单文件 pipeline”的产品定义。

## 具体实现范围

### V1 内必须落地

1. 将 pipeline 收敛为单任务编排执行器。
2. 建立标准阶段计划与阶段状态模型。
3. 建立结构化产物结果模型。
4. 支持通过 `task_id` 查询单任务执行结果。
5. 明确 warnings、error message、duration 等单任务结果语义。

### V1 内暂不落地

1. 不在这一轮处理批量任务生成。
2. 不在这一轮处理统一任务队列调度。
3. 不在这一轮处理高级重试策略。
4. 不在这一轮处理小工具任务执行器。
5. 不在这一轮重做底层算法实现本身。

## 风险与注意事项

- 该功能域如果不收缩为单任务编排执行器，后续功能 3 会很难建立统一的任务系统。
- 如果继续让 pipeline 同时兼管任务创建和执行，任务来源边界会持续混乱。
- 旧接口可能需要经历一段兼容期，但兼容期不应影响新边界的建立。
- 产物模型一旦定义不清，前端任务结果展示、小工具统一化、批处理汇总都会继续分裂。

## 验收标准

- 能编排并执行一个明确的 `pipeline` 任务，而不是直接执行一组散乱路径参数。
- 能输出标准阶段状态，而不只是总成功或失败。
- 能输出结构化产物清单，而不只是单个 `mix_path`。
- 能明确表达跳过、失败、警告、耗时等结果语义。
- 不再由 pipeline 编排执行器承担批处理拆分和任务创建职责。

## 与现有文档的关系

- 本文档是“功能 2：单任务音频汉化流水线编排执行器”的上游计划文档。
- 它明确承接功能 1 产生的输入会话，并为功能 3 的统一任务系统提供任务执行器边界。
- 后续进入实现阶段时，应新增对应执行日志，避免再把批处理编排与单任务执行混写。
