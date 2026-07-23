# [已归档] 功能 1：工作空间与输入管理 V1 计划

## 目标

- 将“工作空间与输入管理”定义为独立功能域，而不是零散附着在 Workbench、Tools、Batch、Voice Lab 等页面中的前置动作。
- 在不继承历史 GUI 调用方式的前提下，为后续所有处理能力提供统一的输入上下文。
- 明确 V1 需要实现的能力边界、API 端点、中间层职责和迁徙规则，作为后续逐项实现与 debug 的唯一基线。

## 背景

- 当前仓库中，文件选择、输出目录推导、同名字幕发现、批处理输入收集、工作目录准备等逻辑主要分散在 `desktop/src/hooks/useFileSelector.ts`、`src/app/services/resource_service.py`、`src/app/services/pipeline_service.py`、`src/app/services/batch_pipeline_service.py`、`src/utils/__init__.py` 等位置。
- 旧 GUI 已从源码树移除；当前需要收束的是 `desktop/` 和 app service 中仍直接消费裸路径的入口，避免输入校验、输出规划、伴随资源发现和任务上下文建立继续分散。
- 当前新桌面前端在浏览器开发态下甚至只能拿到文件名，无法提供后端所需的绝对路径，这说明“文件选择器”本身只是表层症状，真正缺的是完整的输入管理层。
- 因此，V1 不再把它定义为“修一个文件选择器”，而是定义为“建立统一的工作空间与输入会话”。

## 功能定位

该功能域负责在任何实际处理开始前，完成以下事情：

1. 解析运行时工作空间。
2. 接收用户选择的原始输入。
3. 识别输入类型并校验可处理性。
4. 发现可关联的伴随资源。
5. 规划输出目录与临时目录。
6. 建立供后续能力复用的处理会话。

这意味着后续所有处理能力都应优先消费 `session_id` 或标准化后的输入资产，而不是直接消费散乱的裸路径。

## 边界

### 本功能负责

- 工作空间根目录、默认输出目录、默认临时目录、默认模型目录的解析与准备。
- 单文件、多文件、文件夹输入的标准化。
- 音频、字幕、脚本、文件夹等输入类型识别。
- 输入存在性、可读性、基本扩展名合法性校验。
- 同目录或约定目录中的伴随字幕/脚本发现。
- 处理模式判定，例如单音频、批处理、字幕处理、脚本转字幕。
- 输出策略解析与最终输出目录规划。
- 会话对象创建与只读快照返回。

### 本功能不负责

- 不负责实际调用 ASR、翻译、TTS、混音、模型安装等处理能力。
- 不负责页面布局、按钮交互样式、播放器行为。
- 不负责真正的任务调度与进度流转。
- 不负责字幕内容解析、语言识别、音频分析等重处理行为。
- 不负责上传文件二进制内容；V1 只处理本地可访问路径。

## V1 需要实现的功能

### 1. 工作空间解析

系统需要提供统一的工作空间解析能力，用于返回：

- `workspace_root`
- `default_output_root`
- `default_temp_root`
- `default_models_root`

V1 要求：

- 允许从当前项目运行环境解析默认值。
- 允许通过显式参数或配置覆盖默认根目录。
- 统一创建缺失的输出目录、临时目录、模型目录。
- 不再把 `Path.cwd()` 直接当作唯一事实来源。

### 2. 输入资产标准化

系统需要接收原始路径数组，并将其转换为标准输入资产。

V1 支持的输入种类：

- `audio`
- `subtitle`
- `script`
- `folder`
- `unknown`

V1 支持的扩展名范围：

- 音频：`.wav` `.mp3` `.flac` `.m4a` `.ogg` `.aac` `.wma`
- 字幕：`.srt` `.vtt` `.lrc`
- 脚本：`.txt` `.md` `.pdf`

每个输入资产至少需要形成以下信息快照：

- `asset_id`
- `absolute_path`
- `display_name`
- `kind`
- `extension`
- `exists`
- `readable`
- `size_bytes`
- `warnings`
- `validation.errors`

V1 不要求：

- 在这一层做内容级语言识别。
- 在这一层提取完整媒体元数据。
- 在这一层做音频格式转码。

### 3. 伴随资源发现

系统需要提供对伴随资源的显式发现能力，而不是把“顺手找字幕”埋在处理流程内部。

V1 需要支持：

- 在输入音频所在目录查找同名或同 stem 的字幕文件。
- 在约定子目录中查找同名字幕候选，现阶段可以兼容 `ASMR_O` 这类历史目录规则。
- 在目录输入模式下筛出可处理音频文件。

V1 返回的发现结果应包含：

- 候选资源路径
- 候选资源类型
- 匹配理由
- 置信度

V1 不要求自动强绑定，发现结果应作为“建议伴随项”交给会话创建阶段确认。

### 4. 输出策略与目录规划

V1 需要统一三种输出策略：

- `source-nearby`
- `workspace-default`
- `custom-dir`

系统需要根据输入模式和输出策略，解析最终输出目录与临时目录。

V1 目录规划建议：

- 单文件：`<output_root>/<sanitized_input_name>/`
- 多文件：`<output_root>/batch_<timestamp>/`
- 文件夹批处理：`<output_root>/<folder_name>_batch_<timestamp>/`
- 临时目录：`<temp_root>/<session_id>/`

V1 必须满足：

- 由后端统一生成 `resolved_output_dir`
- 前端不再自行拼接输出目录
- 工具箱、工作台、批处理共用同一规则

### 5. 处理会话创建

在工作空间、输入资产、伴随资源、输出策略都已经明确后，系统需要创建一个处理会话。

V1 支持的会话模式：

- `single-audio`
- `multi-audio`
- `folder-batch`
- `subtitle-only`
- `script-to-subtitle`

V1 会话至少应包含：

- `session_id`
- `mode`
- `workspace`
- `input_asset_ids`
- `primary_input_asset_id`
- `companion_asset_ids`
- `resolved_output_dir`
- `resolved_temp_dir`
- `status`
- `validation`

其中：

- `status` 在 V1 只需覆盖 `draft`、`ready`、`invalid`
- `validation` 需要保留 errors / warnings，便于前端直接展示

## 对外 API 设计

V1 建议建立以下端点。

### `POST /api/v1/workspaces/resolve`

用途：

- 解析当前运行时工作空间
- 返回默认根目录与路径策略

请求体示例：

```json
{
  "preferred_output_root": "D:/Output",
  "preferred_temp_root": "D:/Temp",
  "preferred_models_root": "D:/Models"
}
```

响应体至少包含：

- `workspace_id`
- `workspace_root`
- `default_output_root`
- `default_temp_root`
- `default_models_root`

### `POST /api/v1/inputs/inspect`

用途：

- 将原始路径数组转换为标准输入资产
- 返回输入校验结果

请求体示例：

```json
{
  "paths": [
    "D:/Audio/a.wav",
    "D:/Audio/a.srt"
  ]
}
```

响应体至少包含：

- `assets`
- `errors`
- `warnings`

### `POST /api/v1/inputs/discover-companions`

用途：

- 基于某个输入资产查找伴随资源候选

请求体示例：

```json
{
  "asset_id": "asset_1",
  "discovery_scope": [
    "same_dir",
    "legacy_subdir"
  ]
}
```

响应体至少包含：

- `primary_asset_id`
- `suggested_companions`

### `POST /api/v1/sessions`

用途：

- 结合 workspace、input assets、companion assets、output policy 创建可执行会话

请求体示例：

```json
{
  "workspace_id": "ws_xxx",
  "mode": "single-audio",
  "input_asset_ids": ["asset_1"],
  "primary_input_asset_id": "asset_1",
  "companion_asset_ids": ["asset_2"],
  "output_policy": {
    "mode": "workspace-default",
    "custom_output_dir": null
  }
}
```

响应体至少包含：

- `session_id`
- `mode`
- `resolved_output_dir`
- `resolved_temp_dir`
- `validation`
- `status`

## 中间层设计

V1 建议明确拆出三个应用层服务。

### `WorkspaceService`

职责：

- 解析工作空间根目录和默认目录
- 创建输出、临时、模型目录
- 对接配置或环境变量中的路径覆盖项

不负责：

- 输入类型识别
- 文件伴随发现
- 会话模式推导

### `InputCatalogService`

职责：

- 标准化原始输入路径
- 识别输入类型
- 校验存在性和可读性
- 发现伴随资源
- 返回输入资产快照

不负责：

- 输出目录规划
- 任务状态管理
- 真正的媒体处理

### `SessionService`

职责：

- 根据 workspace、input assets、companion assets 和 output policy 创建处理会话
- 解析 `mode`
- 生成最终输出目录与临时目录
- 聚合 validation 结果

不负责：

- 启动 pipeline
- 调用 ASR/TTS/翻译
- 维护任务进度

## 与当前实现的关系

### 可以保留的思路

- `src/app/services/resource_service.py` 中统一准备目录的思路可以保留，但需要升级。
- `src/utils.__init__.find_subtitle_file` 中的同名字幕发现经验可以保留，但要迁移到输入目录能力中。
- `src/app/services/batch_pipeline_service.py` 中部分输出目录命名经验可以复用。

### 必须重写或重组的部分

- `desktop/src/hooks/useFileSelector.ts` 当前只返回文件名，不满足后端路径契约。
- `src/app/services/resource_service.py` 当前仅覆盖 `project_root/output/models`，职责过窄。
- `src/app/services/pipeline_service.py`、`audio_tool_service.py` 等接口直接接受裸 `input_path` 的方式需要逐步迁移为消费会话或标准资产。

### 明确不继承的历史包袱

- 不继承“页面自己拼输出目录”的方式。
- 不继承“调用处理逻辑时顺手找字幕”的方式。
- 不继承“由当前 cwd 推断全部工作空间事实”的方式。
- 不继承“前端本地状态就是任务上下文”的方式。

## 具体实现范围

V1 的落地范围只覆盖输入前置层，不直接触碰真正处理链路。

### V1 内必须落地

1. 新建工作空间解析服务。
2. 新建输入资产标准化服务。
3. 新建会话创建服务。
4. 新增四个 API 端点。
5. 为桌面端提供完整绝对路径输入能力。
6. 统一输出目录与临时目录规划规则。
7. 让 Workbench、Tools、Batch 的输入入口都改为先创建 session。

### V1 内暂不落地

1. 不在这一轮引入文件上传接口。
2. 不在这一轮做语言自动识别。
3. 不在这一轮做媒体深度元数据抽取。
4. 不在这一轮改造任务执行状态机。
5. 不在这一轮重做 Voice Lab 的完整输入流。

## 风险与注意事项

- 这是一个基础能力上移动作，短期内会同时影响 Workbench、Tools、Batch 的调用方式。
- 如果没有先统一 session 契约，后续每个功能都可能继续复制一套自己的输入前置逻辑。
- 旧 GUI 已删除，不应继续作为新能力设计的事实基线。
- Web 开发态无法天然拿到本地绝对路径，这意味着桌面端和浏览器调试模式在 V1 需要明确区分能力边界。

## 验收标准

- 能通过单一入口解析工作空间。
- 能将任意输入路径集合标准化为输入资产列表。
- 能显式返回伴随资源候选，而不是把查找逻辑埋进处理链。
- 能为单文件、多文件、文件夹批处理创建结构一致的处理会话。
- Workbench、Tools、Batch 不再各自维护独立的输出目录规划逻辑。
- 后续处理能力可以消费 `session_id` 或同等标准化上下文，而不是继续直接吃裸路径。

## 与现有文档的关系

- 本文档是“功能 1：工作空间与输入管理”的上游计划文档。
- `docs/feature-E-file-selector.md` 可视为该功能域中的一个局部现象说明，而不是完整设计。
- 后续如果进入具体实现阶段，应新增对应执行日志，避免再把页面级修补与功能域级设计混写。
