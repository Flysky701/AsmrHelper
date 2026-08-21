# 轻量结果预览方案 V1

> 状态：设计草案。当前实现已提供 TaskResult/Preview 和审阅接口，但公共结果字段以 `primary_artifact_id + artifacts` 为准；本文中的方案字段不自动构成 API 契约。

## 目标

- 在不展开复杂结果系统、字幕编辑器或多人审校平台的前提下，先定义一版最小可用结果预览方案。
- 让用户在任务完成后，能够快速完成“看结果、听结果、发现问题、做轻量人工确认”这几个关键动作。
- 为后续功能 8 / 功能 9 的进一步演化保留空间，但当前阶段不把实现负担拉得过重。

## 方案定位

这不是完整的结果系统，也不是完整的人工校对系统。

它只是当前阶段的最小预览方案，解决一个非常具体的问题：

> 一个任务执行完后，用户最少需要看到什么、听到什么、确认什么，才能决定是否继续使用这个结果。

## 适用范围

V1 预览方案主要覆盖：

- `pipeline` 任务结果
- `tool.asr`
- `tool.tts`
- `tool.translate_subtitle`
- `tool.script_to_subtitle`
- 其他已经有明确主产物的单步工具任务

不要求所有任务类型在第一轮都有完全一致的高质量预览体验，但要求至少能进入同一套轻量结果展示框架。

## 核心原则

### 1. 先看主产物，再看中间产物

用户首先应该看到这次任务最重要的结果，而不是被一堆中间文件淹没。

### 2. 先做消费，不做编辑

V1 只解决：

- 查看
- 试听
- 打开文件
- 打开目录
- 人工轻量确认

不解决：

- 编辑字幕
- 精修音频
- cue 级逐条校对
- 多人审校流程

### 3. 失败任务也允许部分预览

如果任务失败，但已经产出了一部分中间结果，V1 仍然允许查看这些结果，而不是只显示“失败”。

## V1 需要支持的动作

### 1. 展示主产物

每个任务结果都应明确一个 `primary_artifact_id`，并在 `artifacts` 中返回完整产物记录。

例如：

- `pipeline`：最终混音音频或最终字幕
- `tool.asr`：转写文本或导出字幕
- `tool.tts`：合成音频
- `tool.translate_subtitle`：译文字幕
- `tool.script_to_subtitle`：生成字幕文件

### 2. 预览主产物

V1 只支持最基础的预览：

- `audio`：试听
- `subtitle`：查看字幕文本
- `text`：查看纯文本结果

### 3. 查看关键中间产物

在主产物之外，可展示有限数量的次级结果，例如：

- `tts_audio`
- `vocals`
- `transcript`
- `bilingual_subtitle`

这些结果默认作为次级内容展示，不抢占主结果位置。

### 4. 查看告警与失败信息

V1 需要明确展示：

- 阶段跳过
- 产物缺失
- warnings
- 失败原因

用户应能快速判断：

- 是任务完全不可用
- 还是主结果可用但某些中间结果没生成

### 5. 人工轻量确认

V1 只允许最轻量的人工确认状态：

- `accepted`
- `needs_review`
- `needs_rework`

并允许一条简短备注。

这里的目标不是做完整人工审校系统，而是给结果一个“人工看过后的最小状态”。

## 预览数据结构草案

V1 可以先约定一个轻量结果预览结构：

```json
{
  "task_id": "task_xxx",
  "primary_artifact_id": "art_mix_001",
  "artifacts": [
    {
      "artifact_id": "art_mix_001",
      "task_id": "task_xxx",
      "type": "audio.mix",
      "path": "D:/output/a_mix.wav",
      "stage": "mix",
      "label": "最终混音",
      "primary": true,
      "preview": true,
      "metadata": {}
    },
    {
      "artifact_id": "art_sub_001",
      "task_id": "task_xxx",
      "type": "subtitle.srt",
      "path": "D:/output/a.srt",
      "stage": "export",
      "label": "字幕文件",
      "primary": false,
      "preview": true,
      "metadata": {}
    }
  ],
  "warnings": [],
  "preview_modes": ["audio", "subtitle"],
  "artifact_count": 2
}
```

## 预览种类

V1 建议只定义 3 种预览类型：

- `audio`
- `subtitle`
- `text`

说明：

- `audio` 用于试听
- `subtitle` 用于展示字幕文本
- `text` 用于展示转写或其他纯文本结果

暂不引入：

- `waveform`
- `timeline_editor`
- `side_by_side_compare`

## 页面层最小交互

V1 只建议提供以下交互：

1. 点击主产物进行预览
2. 点击次级产物进行切换查看
3. 打开文件
4. 打开目录
5. 切换人工确认状态
6. 填写简短备注

## API 草案

V1 可先定义这几个轻量接口：

### `GET /api/v1/tasks/{task_id}/preview`

用途：

- 返回结果预览层所需的最小数据包

### `PATCH /api/v1/tasks/{task_id}/review`

用途：

- 更新人工轻量确认状态；`POST /review-status` 是当前保留的兼容别名

### `PUT /api/v1/tasks/{task_id}/review-note`

用途：

- 更新人工备注；`POST /review-note` 是当前保留的兼容别名

## 明确当前不做的内容

为了控制实现负担，V1 明确不展开：

- cue 级字幕逐条审校
- 字幕在线编辑器
- 波形编辑器
- 双轨 AB 对比
- 片段循环精听系统
- 多人协作审校
- 复杂返工编排

## 与功能 8 / 功能 9 的关系

当前建议先把这份方案视为：

- 功能 8 的结果资产消费草案
- 功能 9 的轻量实现落点

但暂时不要求把功能 8 / 9 完全拆成成熟系统。

## 一句话结论

当前阶段的轻量结果预览方案可以定义为：

> 以主产物为中心，支持基础试听、文本查看、次级结果查看和轻量人工确认，不展开成复杂编辑器或完整审校平台。
