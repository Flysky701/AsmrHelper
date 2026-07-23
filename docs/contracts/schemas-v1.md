# 数据结构契约 v1

> 状态：已落码  
> 原则：只定义跨进程稳定字段；运行时对象、SDK 客户端和本机解析路径不进入公共契约。

## 1. 通用约定

- JSON 字段使用 `snake_case`。
- 时间使用带时区的 ISO 8601 字符串。
- `progress` 范围固定为 `0.0` 到 `1.0`。
- 语言代码当前使用 `ja`、`zh`、`en`；扩展新语言时由能力描述声明。
- 未知字段默认拒绝，Provider 私有扩展只允许进入 `provider_options`。

## 2. PipelineRunCreateRequest

```json
{
  "input": {
    "path": "E:/media/source.mp4",
    "companion_paths": []
  },
  "output": {
    "directory": "E:/media/output"
  },
  "execution_profile": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `input.path` | string | 是 | 主输入文件 |
| `input.companion_paths` | string[] | 否 | 字幕、音轨等伴随文件 |
| `output.directory` | string | 否 | 输出目录；缺省时由后端工作区策略决定 |
| `execution_profile` | ExecutionProfile | 是 | 可持久化的执行意图 |

## 3. ExecutionProfile

```json
{
  "version": 1,
  "source_lang": "ja",
  "target_lang": "zh",
  "skip_existing": false,
  "stages": {
    "separate": {
      "enabled": true,
      "provider": "htdemucs",
      "model": "htdemucs",
      "options": {},
      "provider_options": {}
    },
    "asr": {
      "enabled": true,
      "provider": "faster_whisper",
      "model": "faster-whisper-small",
      "options": {},
      "provider_options": {}
    },
    "translate": {
      "enabled": true,
      "provider": "deepseek",
      "model": "deepseek-chat",
      "options": {},
      "provider_options": {}
    },
    "tts": {
      "enabled": true,
      "provider": "edge",
      "model": null,
      "options": {},
      "provider_options": {}
    },
    "mix": {
      "enabled": true,
      "provider": "ffmpeg",
      "model": null,
      "options": {},
      "provider_options": {}
    },
    "export": {
      "enabled": true,
      "provider": "ffmpeg",
      "model": null,
      "options": {
        "subtitle_format": "srt"
      },
      "provider_options": {}
    }
  }
}
```

`skip_existing` 控制是否复用已存在的阶段输出。混音延迟在标准 `options` 中使用 `tts_delay_ms`，单位固定为毫秒；旧平铺请求中的 `tts_delay` 仍按秒兼容转换。

`StageProfile` 的稳定字段只有：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enabled` | boolean | 是否执行该阶段 |
| `provider` | string | Provider 稳定标识 |
| `model` | string/null | 模型标识；无模型概念时为 `null` |
| `options` | object | 已标准化、可跨 Provider 理解的参数 |
| `provider_options` | object | Provider 私有参数，必须由对应适配器校验 |

API Key、Base URL、本机模型绝对路径、设备句柄和已初始化客户端不属于 `ExecutionProfile`。这些值由设置和运行前解析产生。

## 4. Task

```json
{
  "task_id": "task_01",
  "task_type": "pipeline",
  "state": "running",
  "stage": "asr",
  "progress": 0.35,
  "message": "Transcribing audio",
  "error": null,
  "created_at": "2026-07-23T10:00:00Z",
  "started_at": "2026-07-23T10:00:01Z",
  "finished_at": null,
  "stages": []
}
```

`state` 取值：`pending`、`running`、`completed`、`failed`、`cancelled`。

`stages` 在任务详情中返回，在创建响应和列表中可以省略。单项结构为：

```json
{
  "stage": "asr",
  "state": "running",
  "progress": 0.4,
  "message": "Transcribing audio",
  "started_at": "2026-07-23T10:02:00Z",
  "finished_at": null,
  "error": null
}
```

阶段状态额外允许 `skipped`。

## 5. TaskError

```json
{
  "code": "PROVIDER_CONNECTION_FAILED",
  "stage": "tts",
  "message": "TTS provider returned no audio",
  "retryable": true,
  "detail": "Upstream response contained no audio frames",
  "data": {}
}
```

- `message` 面向用户，必须完整且不得被阶段标签截断。
- `detail` 面向诊断，可以省略，但不得包含密钥。
- `data` 只存机器可读的附加信息，不承担核心语义。
- 多阶段发生错误时，任务保留首个导致失败的错误；完整诊断可通过阶段状态或事件获取。

## 6. Artifact 与 TaskResult

```json
{
  "task_id": "task_01",
  "primary_artifact_id": "artifact_final",
  "artifacts": [
    {
      "artifact_id": "artifact_final",
      "task_id": "task_01",
      "type": "video",
      "path": "E:/media/output/result.mp4",
      "stage": "export",
      "label": "Final Output",
      "primary": true,
      "preview": true,
      "metadata": {
        "mime_type": "video/mp4"
      }
    }
  ],
  "warnings": []
}
```

`path` 是后端管理的本地资源定位信息。桌面端不得根据命名规则猜测产物，应以结果接口返回值为准。

权威结果入口是 `GET /api/v1/tasks/{task_id}/result`。Pipeline 和 Tool 的任务结果入口返回相同结构。`primary_artifact_id` 是唯一的主产物判断依据；`primary` 是同一事实在列表项上的便捷标记。`preview` 只表示后端声明该产物可预览，具体预览模式由 Preview 接口返回，桌面端不得通过扩展名猜测。

旧 `files`、路径型 `primary_output`、`secondary_outputs`、`artifact_type`、`preview_kind` 和 `is_primary` 不属于 v1 公共结果结构，仅可留在内部模型或兼容执行响应。

## 7. ModelStatus

模型文件存在与模型可以执行是两个不同事实：

```json
{
  "model_id": "faster-whisper-base",
  "status": "installed",
  "detail": "Model is installed but runtime requirements are unavailable",
  "executable": false,
  "issues": [
    {
      "code": "PYTHON_DEPENDENCY_MISSING",
      "requirement": "faster_whisper",
      "message": "Python dependency is unavailable: faster_whisper"
    }
  ]
}
```

`status` 表示权重、包或云凭据的安装/配置状态；`executable` 表示当前进程是否具备实际运行条件。模型可以是 `installed` 但 `executable=false`。`issues` 当前稳定使用：

- `MODEL_ASSET_MISSING`
- `MODEL_ASSET_INVALID`
- `PYTHON_DEPENDENCY_MISSING`
- `SYSTEM_TOOL_MISSING`
- `GPU_UNAVAILABLE`
- `CREDENTIAL_MISSING`

桌面端不得把 `installed` 直接显示为“可执行”，也不得等到 Pipeline 运行后才报告已知依赖缺失。

## 8. RuntimeEvent

事件用于诊断和增量展示，不替代 `Task` 事实状态。

```json
{
  "sequence": 12,
  "time": "2026-07-23T10:02:10Z",
  "level": "info",
  "type": "stage_progress",
  "task_id": "pipeline-12",
  "stage": "asr",
  "message": "Decoded segment 24",
  "detail": null,
  "data": {
    "progress": 0.4
  }
}
```

约束：

- `sequence` 在单个任务内严格递增；客户端可用 `after_sequence` 增量续读。
- `level` 当前使用 `info`、`warning`、`error`；`type` 保持字符串扩展点。
- `data` 只放事件附加信息，不复制完整 TaskStatus，也不得包含 secret。
- 模型安装事件使用 `type=model_operation`，`data` 明确包含 `operation`、`model_id`、`state` 和 `progress`。
- `GET /tasks/{task_id}/events` 通过 SSE 推送事件；终态以 `done` 事件携带的 TaskStatus 快照结束。

RuntimeEvent 当前只保存在进程内，用于实时诊断和增量展示；终态历史仍以 SQLite 中的 TaskStatus 与 Artifact 为准。App 启动和任务状态恢复不依赖事件持久化。
