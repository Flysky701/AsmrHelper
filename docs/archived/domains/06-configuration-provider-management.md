# [已归档] 功能 6：配置与提供方接入管理 V1 计划

## 目标

- 将系统默认参数、provider 配置、API 凭据、路径偏好和配置覆盖规则收敛为统一功能域。
- 建立多 ASR / 多 TTS / 多云端 API 共存时可扩展的参数管理模型，避免前端、任务系统和执行器各自定义自己的参数结构。
- 明确参数由谁定义、由谁冻结、由谁注入、由谁消费，确保不重、不漏、不耦合。

## 背景

- 当前仓库已有 `config.json` / `config.example.json` / `src/config.py` 等配置基础，但更多是“配置文件读写”，还不是完整配置功能域。
- 当前 Settings 页面仍然主要是前端本地 state，不是系统真实配置中心。
- 当前 provider 使用点分散在 pipeline、translation、model manager 兼容层、桌面端参数表单等多个位置。
- 当系统需要同时支持多个本地 ASR、多个本地或云端 TTS、多个云端 LLM API 时，参数差异会迅速膨胀。
- 如果继续用平铺字段，例如 `tts_engine`、`translate_provider`、`asr_model`，后续会很难支持 provider 专属参数。

## 功能定位

该功能域是整个系统的“参数定义中心”和“provider 接入中心”。

它负责：

1. 定义能力类别、provider、model 与参数 schema。
2. 管理默认值、路径偏好、provider 接入配置。
3. 对外提供参数描述、配置读写和 provider 配置校验能力。
4. 为功能 3 生成任务时提供标准 `ExecutionProfile` 生成依据。
5. 与功能 5 协作生成执行时所需的 `RuntimeBinding`。

`CapabilityOption`、高级参数、敏感参数、模型字段与 `RuntimeBinding` 的横向约束以 [基础设施契约 V1](../contracts/infrastructure-contracts-v1.md) 为准。

它不直接负责业务执行。

## 边界

### 本功能负责

- 配置 schema 定义。
- provider capability 定义。
- 默认值管理。
- API key / base URL / provider 配置管理。
- 配置加载、保存、校验、脱敏输出。
- `CapabilityDescriptor` 定义与查询。
- `ExecutionProfile` 生成规则。

### 本功能不负责

- 不负责模型是否 ready，这属于功能 5。
- 不负责输入文件识别与会话建立，这属于功能 1。
- 不负责任务排队与调度，这属于功能 3。
- 不负责流水线和工具业务执行，这属于功能 2 和功能 4。
- 不负责前端页面布局本身。

## 项目级参数模型

V1 需要正式确立以下三个对象。

### 1. `CapabilityDescriptor`

职责：

- 表达某个能力类别下某个 provider 支持什么。
- 告诉前端和任务系统该展示和校验哪些参数。

至少应包含：

- `category`
- `provider`
- `kind`
- `supported_models`
- `common_option_schema`
- `provider_option_schema`
- `supports`
- `default_model`

示例：

```json
{
  "category": "tts",
  "provider": "qwen3_tts",
  "kind": "local",
  "supported_models": ["default"],
  "common_option_schema": ["voice", "speed"],
  "provider_option_schema": ["voice_profile_id", "emotion", "temperature"],
  "supports": {
    "voice_clone": true,
    "streaming": false
  },
  "default_model": "default"
}
```

### 2. `ExecutionProfile`

职责：

- 表达“这次任务实际要怎么跑”。
- 在任务创建阶段被冻结，写入 `TaskSpec`。

至少应包含：

- `category`
- `provider`
- `model`
- `common_options`
- `provider_options`

示例：

```json
{
  "category": "asr",
  "provider": "faster_whisper",
  "model": "large-v3",
  "common_options": {
    "language": "ja"
  },
  "provider_options": {
    "disable_vad": true,
    "beam_size": 5
  }
}
```

### 3. `RuntimeBinding`

职责：

- 表达“这次执行真正注入了哪些运行时资源”。
- 由功能 5 和功能 6 在执行瞬间生成，供功能 2 与功能 4 消费。

至少可能包含：

- `api_key`
- `base_url`
- `local_model_path`
- `device`
- `provider_runtime_client`

规则：

- 不写入任务
- 不持久化到队列
- 不在普通查询接口中回显敏感字段

## 参数分层规则

V1 需要将参数正式拆成四层：

1. `category`
   - `asr`
   - `tts`
   - `llm`
   - `separator`

2. `provider`
   - 例如 `faster_whisper`、`edge_tts`、`qwen3_tts`、`openai`、`deepseek`

3. `model`
   - provider 下的具体模型、音色或档位

4. `options`
   - `common_options`
   - `provider_options`

V1 原则：

- 公共参数放 `common_options`
- provider 私有参数放 `provider_options`
- 不允许把所有 provider 的参数平铺在同一个配置对象里

## V1 需要实现的功能

### 1. 统一配置 schema

V1 至少需要管理以下配置组：

`api`
- `provider`
- `deepseek_api_key`
- `openai_api_key`
- `deepseek_base_url`
- `openai_base_url`

`tts`
- `engine`
- `voice`
- `speed`

`paths`
- `output_dir`
- `vtt_dir`
- `model_cache_dir`
- `temp_dir`

`processing`
- `original_volume`
- `tts_volume`
- `tts_delay`
- `vocal_model`
- `asr_model`

### 2. 配置优先级

V1 统一定义：

- `runtime override > env > config file > built-in defaults`

也就是说：

- 任务本次显式覆盖优先级最高
- 环境变量高于本地配置
- 本地配置高于内置默认值

### 3. Provider 接入配置

V1 至少覆盖：

- `deepseek`
- `openai`
- 本地 `asr` provider
- 本地/云端 `tts` provider

V1 要求：

- provider 名称合法性校验
- API key 与 base URL 配置管理
- provider 缺失配置时返回明确错误

### 4. CapabilityDescriptor 查询

系统需要支持按 category/provider 查询能力描述。

用途：

- 前端动态渲染参数表单
- 功能 3 创建任务时生成 `ExecutionProfile`
- 功能 2 与功能 4 在执行前校验参数完整性

能力参数 schema 不只描述字段名，还需要表达 UI 控件、高级参数、敏感参数和是否允许持久化。具体字段见 [基础设施契约 V1](../contracts/infrastructure-contracts-v1.md)。

### 5. ExecutionProfile 生成规则

功能 6 需要定义如何从：

- 默认配置
- 用户输入
- provider 能力描述

生成最终的 `ExecutionProfile`。

V1 原则：

- 默认值由功能 6 提供
- 任务创建时由功能 3 冻结
- 执行器不再自行猜测默认 provider 或默认参数

### 6. 配置保存与脱敏输出

V1 必须支持：

- 读取配置
- 更新配置
- 保存配置
- 校验配置
- 脱敏返回敏感字段

V1 敏感信息规则：

- API key 不在日志中输出
- 普通查询接口不回显明文 key
- 页面读取时区分“已配置”和“具体值”

## 对外 API 设计

### `GET /api/v1/settings`

用途：

- 获取当前配置的脱敏视图

### `PUT /api/v1/settings`

用途：

- 更新并保存配置

### `POST /api/v1/settings/validate`

用途：

- 校验配置是否合法

### `POST /api/v1/settings/test-provider`

用途：

- 测试指定 provider 的接入配置是否有效

### `GET /api/v1/capabilities`

用途：

- 获取所有 `CapabilityDescriptor`

### `GET /api/v1/capabilities/{category}`

用途：

- 按能力类别获取 provider 能力描述

## 中间层设计

### `SettingsService`

职责：

- 配置读取、更新、保存、脱敏输出

### `ProviderConfigService`

职责：

- 管理 provider 配置
- 校验 provider 所需字段

### `CapabilityDescriptorService`

职责：

- 管理各 category/provider 的能力描述
- 对外提供参数 schema 查询

### `ExecutionProfileBuilder`

职责：

- 根据默认值、用户输入和 capability descriptor 生成 `ExecutionProfile`

### `ConfigOverlayService`

职责：

- 统一处理默认值、配置文件、环境变量和运行时覆盖的叠加逻辑

## 与当前实现的关系

### 可以保留的思路

- `src/config.py` 中基础配置结构与读写思路可以保留。
- `config/config.example.json` 可以继续作为默认模板。
- 现有 provider 字段命名与部分默认参数定义可以保留。

### 必须重写或重组的部分

- 当前 Settings 页面只是前端本地 state，需要迁移为真实配置中心。
- 当前 provider 参数使用点分散，需要统一到 capability descriptor 与 execution profile 体系。
- 当前执行器仍偏平铺字段消费，需要逐步迁移到 `ExecutionProfile`。

### 明确不继承的历史包袱

- 不继承“设置页只是 UI 草稿”的方式。
- 不继承“谁需要配置谁自己去读 config”的方式。
- 不继承“所有 provider 共用一套平铺参数字段”的方式。
- 不继承“任务内携带敏感凭据”的方式。

## 具体实现范围

### V1 内必须落地

1. 建立功能 6 的正式配置 schema。
2. 确立配置优先级规则。
3. 建立 capability descriptor 机制。
4. 建立 execution profile 生成规则。
5. 建立 settings 读写与 provider 校验 API。
6. 定义 runtime binding 的生成边界。

### V1 内暂不落地

1. 不在这一轮做多 profile 配置切换。
2. 不在这一轮做复杂加密存储升级。
3. 不在这一轮做远程配置同步。
4. 不在这一轮做复杂 provider capability negotiation。

## 风险与注意事项

- 如果功能 6 不先统一，功能 2、3、4 会持续复制 provider 参数定义。
- 如果 capability descriptor 不清晰，前端表单、任务创建和执行器校验会长期不一致。
- 如果 execution profile 和 runtime binding 不分开，任务持久层和敏感配置会耦合。

## 验收标准

- 配置 schema、provider schema、默认值与覆盖规则有统一定义。
- 前端和任务系统可以基于 capability descriptor 渲染和冻结参数。
- 执行器消费 execution profile，而不是继续消费散乱平铺字段。
- 敏感凭据不进入任务持久层。

## 与现有文档的关系

- 本文档是“功能 6：配置与提供方接入管理”的上游计划文档。
- 它与功能 5 一起构成执行前的参数与运行条件基础。
