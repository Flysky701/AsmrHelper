# [已归档] 功能 4：单步工具执行体系 V1 计划

## 目标

- 将现有零散的小工具能力整理为统一的工具执行器体系，而不是仅仅作为 Tools 页面上的若干按钮。
- 明确工具执行器只负责各自的业务能力，不负责统一排队与调度。
- 为功能 3 提供可注册、可分发、可追踪结果的工具执行器集合。

## 背景

- 当前仓库中，小工具能力分散在 `AudioToolService`、`AsrService`、`TtsService`、`TranslationService`、`ScriptSubtitleService` 等多个 service 中。
- 当前前端 `Tools.tsx` 直接调用多个 API，并在本地创建任务状态，这意味着工具业务与任务系统尚未拆开。
- 当前不同工具返回结构差异较大，有的返回文件路径，有的返回 segments，有的返回分析值，尚未形成统一的工具结果视图。
- 经边界确认后，小工具任务本身应进入功能 3 的统一任务队列，而小工具执行逻辑本身则属于功能 4。

## 功能定位

该功能域是“工具执行器集合”。

它负责：

1. 定义每个工具的业务输入。
2. 执行各自的单步业务处理。
3. 收集并返回结构化结果。
4. 作为功能 3 可分发的执行器注册到系统中。

它不是任务队列本身，也不是页面层。

## 边界

### 本功能负责

- 工具输入模型定义。
- 工具执行前校验。
- 工具业务逻辑调用。
- 工具级产物与结果模型定义。
- 工具执行器注册。

### 本功能不负责

- 不负责统一入队、取消、重试、并发控制，这些属于功能 3。
- 不负责工作空间与输入资产标准化，这些属于功能 1。
- 不负责完整流水线多阶段编排，这些属于功能 2。
- 不负责字幕领域模型、脚本文本领域模型、字幕解析和字幕导出规则定义，这些属于功能 7。
- 不负责前端工具卡片布局与交互样式。

## V1 需要实现的功能

### 1. 工具注册表

系统需要建立统一的工具注册表。

V1 作用：

- 注册所有工具类型。
- 建立 `task_type -> tool executor` 的映射关系。
- 向功能 3 提供分发入口。

### 2. 标准工具任务类型

V1 至少统一以下工具任务类型：

- `tool.separate`
- `tool.convert`
- `tool.split`
- `tool.translate_subtitle`
- `tool.asr`
- `tool.tts`
- `tool.script_to_subtitle`
- `tool.volume_preview`

工具任务同样应通过 `ExecutionProfile` 表达参数，而不是平铺散落的 provider 字段。

V1 规则：

- 工具执行器消费 `ExecutionProfile`
- 工具执行器不自行发明 provider 参数 schema
- 工具执行器不直接读取设置作为“隐式默认值”
- 执行前由功能 5 与功能 6 注入 `RuntimeBinding`

### 3. 工具执行器

V1 至少需要建立以下执行器：

- `SeparationToolExecutor`
- `ConvertToolExecutor`
- `SplitToolExecutor`
- `SubtitleTranslateToolExecutor`
- `AsrToolExecutor`
- `TtsToolExecutor`
- `ScriptSubtitleToolExecutor`
- `VolumePreviewToolExecutor`

每个执行器都应只负责自己的业务能力。

每个执行器都需要能够：

- 校验其对应 `ExecutionProfile` 是否完整
- 校验对应 `provider` 是否支持所给 `provider_options`
- 消费 `RuntimeBinding`

### 4. 统一结果模型

虽然每个工具的业务结果不同，但 V1 需要在外层统一结果包装。

V1 统一结果至少应包含：

- `task_id`
- `tool_name`
- `status`
- `artifacts`
- `summary`
- `warnings`
- `error_message`
- `duration_seconds`

对于分析类工具，例如音量预览，可以在 `summary` 或 `metadata` 中返回推荐值。

## 工具能力范围

### 人声分离

输入：

- 主音频文件
- 分离模型
- 可选 stem 列表

输出：

- `vocals`
- 可选其他 stems
- 主输出路径

### 音频转码

输入：

- 输入音频
- 输出路径
- 目标格式
- 采样率
- 声道数

输出：

- 转码文件
- 格式信息
- 时长

### 按字幕切分音频

输入：

- 音频文件
- 字幕文件
- 输出目录
- padding

输出：

- 片段文件列表
- 每段时间轴与文本
- 总片段数

### 字幕翻译

输入：

- 字幕文件
- provider
- source_lang
- target_lang
- bilingual

输出：

- 输出字幕文件
- segment 数
- provider 信息

### 独立 ASR

输入：

- 音频文件
- ASR 模型
- 语言
- 输出路径

输出：

- segments
- text
- 可选字幕输出

### 独立 TTS

输入：

- 文本文件
- TTS 引擎
- voice
- 输出路径

输出：

- 合成音频
- engine
- voice

### 脚本转字幕

输入：

- 脚本文件
- 可选音频
- 可选已有 VTT
- 输出格式
- vertical_mode
- use_llm_clean

输出：

- 字幕文件或文本结果
- 行数
- 运行模式

说明：

- 这里的工具执行器只是“脚本转字幕任务入口”。
- 真正的脚本转字幕领域逻辑归属功能 7。

### 音量预览

输入：

- 原音频
- 可选 TTS 音频
- 当前混音参数

输出：

- RMS
- 推荐原音音量
- 推荐 TTS 比例

## 对外 API 设计

V1 可以允许保留当前分散 API，但内部执行器需要统一。

### 当前兼容端点

- `/api/v1/tools/separate`
- `/api/v1/tools/convert`
- `/api/v1/tools/split`
- `/api/v1/tools/translate-subtitle`
- `/api/v1/tools/volume-preview`
- `/api/v1/asr/transcribe`
- `/api/v1/tts/synthesize`
- `/api/v1/subtitles/script-to-vtt`

### 长期统一方向

长期建议统一为：

- `POST /api/v1/tool-runs`
- `GET /api/v1/tool-runs/{task_id}`

但 V1 不要求同轮重构所有路由，只要求内部执行器边界明确。

## 中间层设计

### `ToolRegistry`

职责：

- 注册工具执行器
- 建立工具类型映射
- 提供执行器查找能力
- 暴露工具对 `CapabilityDescriptor` 的消费关系

### 工具执行器集合

职责：

- 接收标准工具任务
- 执行业务逻辑
- 返回结构化结果

## 与当前实现的关系

### 可以保留的思路

- `AudioToolService` 作为多种音频工具 facade 的思路可以保留。
- `AsrService`、`TtsService`、`TranslationService`、`ScriptSubtitleService` 各自已有单能力外观，可作为执行器内部依赖。
- 当前现有 API 端点可以在兼容期内继续保留。

### 必须重写或重组的部分

- 前端 `Tools.tsx` 当前自己维护本地任务对象，需要迁移为调用功能 3 的任务创建接口。
- 不同工具的结果结构需要补一层统一包装。
- 当前工具能力散在多个 service 中，需要通过注册表统一管理。
- 当前工具参数仍偏平铺，需要迁移为 `ExecutionProfile` 驱动。

### 明确不继承的历史包袱

- 不继承“工具页自己就是任务系统”的方式。
- 不继承“每个工具返回完全不同外层协议而无统一包装”的方式。
- 不继承“路由长什么样就等于工具边界”的方式。

## 具体实现范围

### V1 内必须落地

1. 建立工具注册表。
2. 为主要工具建立独立执行器。
3. 将工具执行结果统一包装。
4. 让功能 3 能基于 `task_type` 分发到工具执行器。

### V1 内暂不落地

1. 不在这一轮统一所有工具外部 HTTP 路由风格。
2. 不在这一轮重做所有工具页面 UI。
3. 不在这一轮要求所有工具都完全切换为 session-only 输入。
4. 不在这一轮做复杂工具链编排。

## 风险与注意事项

- 如果功能 4 不独立出来，功能 3 最终会被迫了解过多工具内部细节。
- 如果工具结果不统一包装，任务系统和结果展示层会继续分裂。
- 如果继续让前端直接拼工具任务，后台任务体系会长期不完整。

## 验收标准

- 主要小工具都拥有明确的执行器边界。
- 小工具任务能被功能 3 的统一任务队列分发执行。
- 工具业务逻辑与任务系统逻辑被明确拆开。
- 工具结果对外具备统一包装模型。

## 与现有文档的关系

- 本文档是“功能 4：单步工具执行体系”的上游计划文档。
- 它明确作为功能 3 的执行器来源之一存在，并与功能 2 的流水线编排执行器区分开来。
