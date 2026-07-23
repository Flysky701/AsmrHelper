# [已归档] 功能 7：字幕与文本资产管理 V1 计划

## 目标

- 将字幕解析、字幕标准化、双语字幕组装、脚本转字幕、字幕导出等能力从流水线与工具入口中抽离为独立功能域。
- 明确字幕相关逻辑的唯一业务归属，避免功能 2、功能 3、功能 4 各自维护一套字幕结构与处理规则。
- 让字幕资产成为系统中的一等中间产物，可被单任务流水线、单步工具和结果浏览共同消费。

## 背景

- 当前仓库的字幕相关能力已经主要迁入 `src/core/subtitles/`，但 app service 和兼容入口仍需要继续收口：
  - `src/app/services/subtitle_service.py`
  - `src/app/services/script_subtitle_service.py`
  - `src/core/subtitles/generator.py`
  - `src/core/subtitles/script_processor.py`
  - `src/core/subtitles/script_to_subtitle.py`
  - `src/core/translate/__init__.py` 中的字幕加载、清洗、语言检测逻辑
- 当前桌面前端已经有字幕相关 API 和工具入口：
  - `desktop/src/api/subtitles.ts`
  - `desktop/src/api/tools.ts`
  - `desktop/src/pages/tools/Tools.tsx`
- 当前字幕能力同时出现在 3 个位置：
  - 流水线阶段里
  - 工具页入口里
  - 队列任务类型里
- 如果不单独设立功能域，后续会持续出现这些问题：
  - 同一字幕文件被不同模块按不同数据结构解析
  - 脚本转字幕和字幕导出被误当成纯工具动作
  - 双语字幕组装逻辑在 pipeline 和 tool 中重复实现
  - 队列层误承接字幕业务语义

## 功能定位

功能 7 是字幕与文本相关业务的唯一归属层。

它负责：

1. 定义字幕和文本资产模型。
2. 解析字幕和脚本文本输入。
3. 标准化与清洗字幕内容。
4. 组装双语字幕和文本对齐结果。
5. 导出字幕资产。
6. 向功能 2 和功能 4 提供稳定的字幕领域能力。

它不负责统一排队调度，也不直接扮演页面工具入口。

## 与功能 2/3/4 的关系

这部分必须明确，否则会再次重叠。

### 与功能 2 的关系

- 功能 2 会消费功能 7 的字幕能力。
- 例如：
  - ASR 后生成字幕资产
  - 翻译后生成双语字幕资产
  - 最终导出字幕文件
- 但功能 2 不拥有字幕领域模型，也不定义字幕格式规则。

### 与功能 3 的关系

- 功能 3 只负责把字幕相关动作建模为任务并放入统一队列。
- 例如：
  - `tool.translate_subtitle`
  - `tool.script_to_subtitle`
  - 后续 `tool.subtitle_clean`
  - 后续 `tool.subtitle_export`
- 功能 3 不负责字幕解析、字幕清洗、字幕导出、双语组装本身。

### 与功能 4 的关系

- 功能 4 负责将字幕领域能力包装成单工具执行器。
- 例如：
  - `SubtitleTranslateToolExecutor`
  - `ScriptSubtitleToolExecutor`
  - 后续 `SubtitleCleanToolExecutor`
- 功能 4 不拥有字幕数据结构和字幕领域规则，只调用功能 7。

## 边界

### 本功能负责

- 字幕资产模型定义
- 文本资产模型定义
- SRT / VTT / LRC 的解析与标准化
- 脚本文本的分段与结构化
- 字幕清洗与规范化
- 双语字幕组装
- 字幕格式转换与导出
- 统一的字幕领域校验规则

### 本功能不负责

- 不负责统一任务入队、并发、取消、重试，这属于功能 3
- 不负责完整流水线编排，这属于功能 2
- 不负责把字幕能力包装成工具任务入口，这属于功能 4
- 不负责 provider 参数 schema 与默认值定义，这属于功能 6
- 不负责模型 ready 状态与运行资源检查，这属于功能 5

## V1 需要实现的功能

### 1. 字幕资产模型

V1 需要把字幕从“若干 dict”升级成稳定资产模型。

建议至少定义：

- `SubtitleDocument`
- `SubtitleCue`
- `SubtitleTextBlock`
- `BilingualSubtitleDocument`
- `ScriptDocument`

其中 `SubtitleCue` 至少应包含：

- `cue_id`
- `start`
- `end`
- `text`
- `speaker`
- `lang`
- `metadata`

其中 `BilingualSubtitleDocument` 至少应能表达：

- 原文 cue 列表
- 译文 cue 列表
- 对齐后的 bilingual pair

### 2. 字幕解析与导入

V1 至少支持以下输入：

- `.srt`
- `.vtt`
- `.lrc`
- `.txt`
- `.md`
- 由功能 1 发现并关联的字幕或脚本文本资产

解析结果必须统一转成字幕领域对象，而不是继续让各模块直接使用原始字符串和裸 dict。

### 3. 脚本转字幕

这里要特别明确：

- 脚本转字幕是字幕领域能力，不是工具层私有逻辑。
- 工具页中的“脚本转字幕”只是它的一个任务入口。

V1 建议支持三种模式：

1. 纯脚本分段
   - 根据文本结构切分为 cue
2. 参考现有字幕生成
   - 基于现有时间轴重组文本
3. 结合音频或识别结果对齐
   - 为后续扩展预留

### 4. 字幕标准化与清洗

V1 需要统一以下规则：

- 编码与换行处理
- 空 cue 过滤
- 时间轴顺序校验
- 非法时间段处理
- 文本清洗
- 标点规范化
- 语言标记与来源标记

这一层应吸收当前 `subtitle_cleaner`、`subtitle_strategy` 和 `translate` 模块中散落的清洗规则。

### 5. 双语字幕组装

V1 应支持：

- 单语字幕翻译后组装双语字幕
- ASR 结果与翻译结果配对
- 保持时间轴稳定
- 导出为双语 SRT / VTT

这部分不能只留在流水线私有逻辑里，因为工具与结果浏览同样需要消费。

### 6. 字幕导出与格式转换

V1 至少支持：

- `SubtitleDocument -> srt`
- `SubtitleDocument -> vtt`
- `SubtitleDocument -> lrc`
- `BilingualSubtitleDocument -> srt`
- `BilingualSubtitleDocument -> vtt`

导出层负责统一格式细节，不再由 pipeline worker、GUI worker、工具页各自生成文本。

## API 设计

功能 7 应有自己的字幕领域 API，而不是完全依附工具 API。

### `POST /api/v1/subtitles/load`

用途：

- 加载字幕文件或脚本文本
- 返回标准化字幕或文本资产

### `POST /api/v1/subtitles/parse`

用途：

- 显式将输入内容解析为字幕领域对象
- 便于后续独立编辑、导出、调试

### `POST /api/v1/subtitles/normalize`

用途：

- 对字幕做标准化与清洗

### `POST /api/v1/subtitles/translate`

用途：

- 对字幕文档执行翻译并生成译文资产

### `POST /api/v1/subtitles/bilingualize`

用途：

- 根据原文与译文组装双语字幕文档

### `POST /api/v1/subtitles/export`

用途：

- 将字幕文档导出为目标格式

### `POST /api/v1/subtitles/script-to-subtitle`

用途：

- 将脚本文本转换为字幕资产或字幕文件

说明：

- 工具页可以继续临时兼容旧入口
- 但长期应逐步以字幕领域 API 为主

## 中间层设计

### `SubtitleAssetService`

职责：

- 统一字幕文档与 cue 的领域模型
- 提供解析后的资产对象

### `SubtitleParserService`

职责：

- 解析 SRT / VTT / LRC / 文本文档
- 统一时间轴与文本结构

### `SubtitleNormalizationService`

职责：

- 清洗文本
- 修复和校验时间轴
- 产出标准化字幕文档

### `SubtitleAlignmentService`

职责：

- 原文与译文的对齐
- 双语字幕组装
- 未来音频辅助对齐的扩展点

### `SubtitleExportService`

职责：

- 将字幕文档导出为 SRT / VTT / LRC
- 统一格式细节

### `ScriptSubtitleDomainService`

职责：

- 处理脚本转字幕的领域逻辑
- 不直接扮演工具执行器

## 与当前实现的关系

### 可以保留的思路

- `src/app/services/subtitle_service.py` 中已有的文档化方向
- `src/app/services/script_subtitle_service.py` 中脚本转字幕的应用入口思路
- `src/core/subtitles/generator.py` 中导出格式生成能力
- `src/core/translate/__init__.py` 中对多字幕格式的加载经验
- `src/core/translate/subtitle_cleaner.py` 中的清洗规则

### 必须重组或迁移的部分

- 当前字幕解析逻辑仍有部分散落在 `translate`、`subtitle_service` 和兼容工具入口中，需要继续收敛到功能 7
- `script_subtitle_service.py` 当前应只作为应用入口，不能继续引用已删除的旧 `src.core.script_to_subtitle`
- `script-to-vtt` 的业务逻辑不能继续只作为工具动作存在
- 双语字幕组装不能只作为 pipeline 私有阶段结果
- 格式导出不能继续由多个模块各自拼接字符串

### 明确不继承的历史包袱

- 不继承“字幕只是 pipeline 的附属文件”的认知
- 不继承“字幕类工具自己拥有一套字幕规则”的方式
- 不继承“队列里出现 subtitle 任务类型，就等于队列拥有字幕业务”的误解
- 不继承“脚本转字幕只是一个按钮，不是领域能力”的方式

## V1 内必须落地

1. 正式定义字幕领域资产模型
2. 统一 SRT / VTT / LRC 解析入口
3. 统一字幕标准化和清洗入口
4. 明确脚本转字幕的领域归属
5. 统一字幕导出与格式转换能力
6. 为功能 2 和功能 4 提供稳定字幕领域服务

## V1 内暂不落地

1. 不在这一轮做完整的字幕可视化编辑器
2. 不在这一轮做复杂 speaker diarization 字幕结构
3. 不在这一轮做高级时间轴自动对齐算法
4. 不在这一轮做字幕版本历史管理

## 一句话结论

功能 7 可以正式定义为：

> 字幕与文本资产管理 = 统一拥有字幕和脚本文本的领域模型、解析、清洗、组装与导出能力，并作为流水线与工具系统共同依赖的字幕业务中心。
