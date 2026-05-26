# AsmrHelper 主链路 V1 契约

日期：2026-05-27

## 1. 契约目的

本文只约定当前阶段最重要的一条端到端主链路：

```text
Workbench 选择输入
-> 创建 pipeline task
-> 后端执行
-> TaskCenter 展示状态与阶段
-> Artifact 输出
-> 预览 / 播放 / 人工确认
```

它不是新的功能域总表，也不替代已有领域文档。它的作用是把功能 1、2、3、8、9 中与当前桌面端主链路直接相关的最小稳定面收束出来，作为后续分步实现和验收的共同基线。

## 2. 文档关系

主链路契约依赖以下文档：

- [功能架构总览](functional-architecture-overview.md)：定义功能域边界。
- [API 契约总表](api-contract.md)：定义长期主接口和兼容接口。
- [Service 映射总表](service-layer-mapping.md)：定义现有服务迁移方向。
- [字段契约约束 V1](field-contracts-v1.md)：定义 Task、Service、Capability、TTS、Artifact 等横向字段约束。
- [主链路 V1 数据参数契约](mainline-v1-data-parameters.md)：定义 Session、TaskSpec、ExecutionProfile、RuntimeBinding 的字段、默认值和旧字段映射。
- [单任务流水线编排执行器](../domains/02-pipeline-executor.md)：定义 pipeline 执行器职责。
- [统一任务生成与任务队列](../domains/03-task-generation-queue.md)：定义任务生命周期。
- [结果资产与产物索引管理](../domains/08-result-artifact-index.md)：定义产物结构。
- [结果预览、浏览与人工校对](../domains/09-preview-review.md)：定义结果消费方式。

当本文与领域文档发生冲突时，优先按领域文档修正本文；当代码实现与本文发生冲突时，优先修正文档或代码，使主链路重新回到一致状态。

## 3. 当前阶段边界

### 本契约覆盖

- 桌面端 `desktop/` 的 Workbench 创建 pipeline 任务。
- TaskCenter 查询任务、展示阶段、取消、重试。
- 任务完成后展示主产物和次级产物。
- 轻量预览，包括音频播放、字幕查看、打开结果位置、人工确认状态。

### 本契约暂不覆盖

- 已删除的旧 GUI `src/gui/`；当前契约不会为它恢复兼容路径。
- 完整批处理体验。
- 单步工具页面的全部能力。
- 完整人工字幕编辑器。
- 多人审核、版本管理、复杂回滚。
- 大规模重写已迁移 core 的内部算法实现。

## 4. 主链路阶段

V1 使用以下阶段名作为前后端共同语言：

| stage | 显示名 | 说明 |
|---|---|---|
| `prepare` | 准备输入 | 解析输入、输出目录、伴随字幕或脚本 |
| `separate` | 人声分离 | 可选阶段 |
| `asr` | 语音识别 | 生成转写或字幕基础文本 |
| `translate` | 字幕翻译 | 可选或按配置执行 |
| `tts` | 语音合成 | 生成目标语音 |
| `mix` | 混音输出 | 生成最终音频 |
| `export` | 导出产物 | 汇总 artifact 与 preview 信息 |

TaskCenter 可以展示更短的中文阶段名，但不应该自行发明新的阶段语义。

## 5. Workbench 创建任务契约

### 长期主路径

长期主路径应收束为：

```text
POST /api/v1/sessions
POST /api/v1/tasks
```

其中 `sessions` 负责输入和输出环境，`tasks` 负责创建标准后台任务。

### V1 最小 TaskSpec

Workbench 创建 pipeline 任务时，最小任务定义如下：

```json
{
  "task_type": "pipeline",
  "task_source": "desktop.workbench",
  "session_id": "session_xxx",
  "input_asset_id": "asset_xxx",
  "companion_asset_ids": [],
  "execution_profile": {
    "profile_version": "mainline.v1",
    "source_lang": "ja",
    "target_lang": "zh-CN",
    "stages": {
      "separate": true,
      "asr": true,
      "translate": true,
      "tts": true,
      "mix": true,
      "export": true
    },
    "profiles": {
      "asr": {
        "category": "asr",
        "provider": "faster_whisper",
        "model": "base",
        "common_options": {
          "language": "ja"
        },
        "provider_options": {}
      },
      "translation": {
        "category": "llm",
        "provider": "deepseek",
        "model": "default",
        "common_options": {
          "source_lang": "ja",
          "target_lang": "zh-CN"
        },
        "provider_options": {}
      },
      "tts": {
        "category": "tts",
        "provider": "edge_tts",
        "model": "default",
        "common_options": {
          "voice": "zh-CN-XiaoxiaoNeural",
          "speed": 1.0
        },
        "provider_options": {}
      }
    },
    "skip_existing": false
  }
}
```

字段、默认值、旧字段映射和敏感参数边界以 [主链路 V1 数据参数契约](mainline-v1-data-parameters.md) 为准。本文中的 JSON 只表达主链路对象关系，不作为完整字段表。

### V1 兼容入口

当前仍可保留以下兼容入口：

```text
POST /api/v1/pipeline/run
POST /api/v1/pipeline/batch
```

兼容入口只用于平滑迁移，不继续承载新的长期字段设计。新增字段应优先进入 `TaskSpec`、`Session` 或 `ExecutionProfile`。

## 6. 任务状态契约

TaskCenter 至少依赖以下任务状态字段：

```json
{
  "task_id": "task_xxx",
  "task_type": "pipeline",
  "state": "running",
  "stage": "asr",
  "progress": 42,
  "message": "正在识别语音",
  "detail": "",
  "created_at": "2026-05-27T12:00:00+08:00",
  "started_at": "2026-05-27T12:00:05+08:00",
  "finished_at": null,
  "error": null,
  "artifact_set_id": null
}
```

### state 枚举

| state | 说明 |
|---|---|
| `pending` | 已创建，等待执行 |
| `running` | 正在执行 |
| `completed` | 成功完成 |
| `failed` | 执行失败 |
| `cancelled` | 用户取消 |
| `skipped` | 因策略跳过 |

### progress 规则

- `progress` 使用 `0.0-1.0` 浮点数，与当前 `TaskStatusResponse` 保持一致。
- `completed` 必须为 `1.0`。
- `failed / cancelled / skipped` 可以保留最后进度。
- 前端不得只凭 `progress` 判断任务是否成功，必须以 `state` 为准。
- 前端展示百分比时自行乘以 `100`。

### error 结构

失败任务应尽量返回结构化错误：

```json
{
  "code": "ASR_MODEL_NOT_READY",
  "stage": "asr",
  "message": "ASR 模型不可用",
  "recoverable": true,
  "hint": "请在引擎与资源页面检查模型状态"
}
```

## 7. 任务查询与动作契约

TaskCenter V1 需要稳定消费以下接口：

```text
GET /api/v1/tasks
GET /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/cancel
POST /api/v1/tasks/{task_id}/retry
GET /api/v1/tasks/{task_id}/artifacts
GET /api/v1/tasks/{task_id}/preview
```

如果当前实现仍通过 `pipeline-runs` 或旧 `pipeline` 接口返回数据，需要在适配层映射为本文定义的任务状态结构。

## 8. Artifact 契约

任务完成或部分失败时，后端应返回 `ArtifactSet`。

```json
{
  "artifact_set_id": "artifact_set_xxx",
  "task_id": "task_xxx",
  "primary_artifact_id": "artifact_mix",
  "items": [
    {
      "artifact_id": "artifact_mix",
      "kind": "mixed_audio",
      "stage": "mix",
      "role": "primary",
      "path": "D:/output/demo_mix.wav",
      "media_type": "audio/wav",
      "available": true,
      "preview_kind": "audio"
    },
    {
      "artifact_id": "artifact_subtitle",
      "kind": "subtitle",
      "stage": "export",
      "role": "supporting",
      "path": "D:/output/demo_zh.vtt",
      "media_type": "text/vtt",
      "available": true,
      "preview_kind": "subtitle"
    }
  ],
  "warnings": []
}
```

### artifact kind 建议

| kind | 说明 |
|---|---|
| `mixed_audio` | 最终混音音频 |
| `subtitle` | 字幕文件 |
| `transcript` | 转写文本 |
| `translation` | 翻译文本 |
| `tts_audio` | TTS 中间音频 |
| `stem_audio` | 人声 / 伴奏等分离产物 |
| `debug_file` | 排障文件 |

### 产物展示规则

- `role=primary` 的产物在 TaskCenter 最先展示。
- `available=false` 的产物可以展示缺失原因，但不能给可点击播放入口。
- 前端不应通过文件名猜测主产物，应使用 `primary_artifact_id` 或 `role`。

## 9. Preview 契约

预览层消费 Artifact，不重新定义 Artifact。

`GET /api/v1/tasks/{task_id}/preview` 应返回轻量预览入口：

```json
{
  "task_id": "task_xxx",
  "primary_preview": {
    "artifact_id": "artifact_mix",
    "preview_kind": "audio",
    "title": "demo_mix.wav",
    "uri": "D:/output/demo_mix.wav"
  },
  "items": [
    {
      "artifact_id": "artifact_subtitle",
      "preview_kind": "subtitle",
      "title": "demo_zh.vtt",
      "uri": "D:/output/demo_zh.vtt"
    }
  ],
  "review": {
    "status": "unreviewed",
    "note": ""
  }
}
```

### preview_kind 枚举

| preview_kind | 用途 |
|---|---|
| `audio` | 播放器试听 |
| `subtitle` | 字幕查看 |
| `text` | 普通文本查看 |
| `folder` | 打开输出目录 |
| `none` | 不支持预览，仅展示路径或状态 |

## 10. 前端约束

### Workbench

- 只负责创建任务，不直接实现 pipeline 执行逻辑。
- 不保存后端无法识别的私有参数语义。
- 高级参数可以存在，但必须最终进入 `execution_profile`。
- 文件选择结果应先归入 session / input asset；兼容阶段可继续传 `input_path`。

### TaskCenter

- 只按任务状态和 Artifact 展示结果。
- 不通过日志文本推断真实状态。
- 不通过文件名猜测主产物。
- 日志只作为排障材料，不能成为任务状态的唯一来源。

## 11. 执行顺序

当前阶段建议按以下顺序实施：

1. 先让 `docs` 以本文为中心完成主链路契约收束。
2. 将当前兼容接口返回值适配到任务状态契约。
3. 让 Workbench 创建任务时逐步迁移到 `session + task`。
4. 让 TaskCenter 以 `tasks + artifacts + preview` 为唯一显示基线。
5. 再处理批量任务、单步工具和更复杂的人工校对流。

## 12. 验收标准

主链路 V1 可以认为完成，当且仅当：

- Workbench 创建一个 pipeline 任务后，前端能拿到稳定 `task_id`。
- TaskCenter 能通过任务接口展示 `state / stage / progress / message`。
- 任务终态能稳定区分 `completed / failed / cancelled / skipped`。
- 成功任务能通过 ArtifactSet 找到主产物。
- 预览入口只消费 Artifact，不重新猜测输出文件。
- 旧接口仍可兼容，但新增能力不再继续围绕旧接口扩张。
