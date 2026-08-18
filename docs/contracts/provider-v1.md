# Provider 与设置契约 v1

新增 Provider 或模型参照 [Provider / Model 轻量接入流程](provider-model-onboarding.md)：先核对上游 API 并完成 Server 最小验证，再由客户端消费能力描述。

> 状态：已落码  
> 适用范围：设置 API、能力发现、Provider 适配器、运行前检查

## 1. 边界

Provider 层负责：

- 声明自身能力、模型和可配置项；
- 校验标准参数及私有参数；
- 将稳定契约转换为第三方 SDK 或本地工具调用；
- 将外部异常转换为统一 `TaskError`；
- 在运行前解析密钥、模型路径和设备。

桌面端不得直接依赖第三方 SDK 字段，也不得保存运行时客户端对象。

## 2. 设置 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/settings` | 获取脱敏设置 |
| `PUT` | `/api/v1/settings` | 更新设置 |
| `POST` | `/api/v1/settings/validate` | 仅做结构和取值校验 |
| `POST` | `/api/v1/settings/test-provider` | 对指定 Provider 做真实可用性测试 |

读取和更新响应统一使用：

```json
{
  "settings": {
    "providers": {
      "default_llm": "deepseek",
      "deepseek": {
        "base_url": "https://api.deepseek.com",
        "credential_configured": true
      },
      "openai": {
        "base_url": "https://api.openai.com/v1",
        "credential_configured": false
      }
    }
  }
}
```

密钥写入时可以作为写专用字段提交，但读取时不得返回原文，也不得用 `"***configured***"` 冒充密钥值。桌面端通过 `credential_configured` 展示配置状态。

更新请求：

```json
{
  "settings": {
    "providers": {
      "default_llm": "deepseek",
      "deepseek": {
        "base_url": "https://api.deepseek.com",
        "credential": "write-only-api-key"
      }
    }
  }
}
```

`credential` 是写专用字段。省略或传空字符串表示保持已保存凭据不变，不表示清除。`validate` 同样接收 `{ "settings": ... }`，但不持久化。

Provider 测试请求与响应：

```json
{
  "provider": "deepseek",
  "settings": {
    "providers": {
      "deepseek": {
        "base_url": "https://api.deepseek.com",
        "credential": "optional-unsaved-key"
      }
    }
  }
}
```

```json
{
  "provider": "deepseek",
  "success": true,
  "error_code": null,
  "message": "deepseek 连接与鉴权验证成功",
  "errors": []
}
```

当前 DeepSeek/OpenAI 均按 OpenAI-compatible 接口执行带超时的轻量模型列表请求。测试可使用尚未保存的草稿凭据和 Base URL；失败返回稳定 `error_code`，不得在响应中回显凭据。

## 3. 能力描述

```json
{
  "category": "tts",
  "provider": "edge",
  "models": [],
  "default_model": null,
  "options": [
    {
      "name": "voice",
      "type": "string",
      "required": true,
      "default": null,
      "enum": [],
      "min": null,
      "max": null,
      "advanced": false,
      "secret": false
    }
  ]
}
```

能力描述只表达稳定约束。桌面端可据此生成基础控件，但最终校验仍由后端完成。

`CapabilityOption` 固定包含 `name/type/required/default/description/enum/min/max/advanced/secret`。Provider 私有参数默认标记为 `advanced=true`；凭据仍属于 Settings，不得因为 `secret=true` 就混入 ExecutionProfile。

第三方模型列表容易变化，不在公共文档中固化为完整枚举；Provider 可以动态返回当前可用模型。默认模型必须是实际可发送给 Provider 的模型标识，`"default"` 等 UI 占位值不得进入外部请求。

## 4. 参数分层

1. `options`：跨 Provider 已标准化的参数，如语言、音量或温度。
2. `provider_options`：对应适配器独有的参数。
3. Settings：凭据、Base URL、缓存目录和设备偏好。
4. RuntimeBinding：运行前解析出的密钥、本机绝对路径、设备和客户端，仅在后端进程内存在。

`voice_profile_id` 等参数必须只在一个层级拥有权威位置。若它代表可复用资产引用，应作为标准 `options`；若只对单个 Provider 有意义，则放入 `provider_options`，不得两处同时定义。

## 5. 运行前检查

每个实际启用的阶段在执行前必须完成：

- Provider 是否存在；
- 必填配置和凭据是否存在；
- 模型标识是否有效或可解析；
- 本地依赖、模型文件和设备是否可用；
- 关键输入格式是否受支持。

`test-provider` 必须执行足以证明可用性的真实测试，例如轻量 API 请求或最小本地推理；只检查“已填写 API Key”不能视为测试成功。

## 6. 统一错误代码

至少使用以下稳定代码：

| 错误代码 | 含义 |
| --- | --- |
| `PROVIDER_NOT_FOUND` | Provider 未注册 |
| `PROVIDER_CREDENTIAL_MISSING` | 缺少凭据 |
| `PROVIDER_CONNECTION_FAILED` | 无法连接或鉴权失败 |
| `PROVIDER_MODEL_INVALID` | 模型不存在或不可用 |
| `PROVIDER_DEPENDENCY_MISSING` | Python 包、可执行文件或模型资源缺失 |
| `PROVIDER_RESPONSE_INVALID` | 返回内容不符合预期，例如 TTS 未返回音频 |
| `PROVIDER_PARAMETER_INVALID` | 参数无法由适配器接受 |

外部错误原文可以进入脱敏后的 `detail`，但对桌面端展示的 `message` 必须稳定、可理解。

## 7. 当前稳定标识

- TTS：`edge`、`qwen3`、`voxcpm2`
- ASR：`faster_whisper`、`fun_asr`、`qwen3_asr`
- 分离：Provider 为 `demucs`，模型为 `htdemucs`
- 翻译：`deepseek`、`openai`
- 媒体处理：`ffmpeg`

稳定标识表示契约和注册名称可使用，不表示当前机器已经安装或完成真实推理验收。各 Provider 的当前状态见 [多引擎支持现状](../roadmap/multi-engine-status.md)。

如需重命名 Provider，必须在兼容层保留旧标识映射，不得只改桌面端或文档中的单侧名称。
