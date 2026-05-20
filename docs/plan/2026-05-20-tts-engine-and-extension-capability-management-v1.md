# 功能 10：TTS 引擎管理与扩展能力管理 V1 计划

## 目标

- 将 TTS 相关能力从“单一合成接口 + 某些引擎专属音色功能”的混合状态，整理为统一的 TTS 引擎管理功能域。
- 明确哪些能力属于所有 TTS 引擎的通用能力，哪些能力只是某些引擎的扩展能力。
- 避免将音色资产、音色克隆、参考音频分析、profile 试听等能力误定义为全局稳定产品能力。

## 背景

- 当前仓库已经有稳定的 TTS 合成入口：
  - `src/app/services/tts_service.py`
  - `src/api/http/routes/tts.py`
- 同时也已经存在一组明显带有引擎依赖性的扩展能力：
  - `src/app/services/voice_service.py`
  - `src/api/http/routes/voice.py`
  - `src/core/tts/voice_profile.py`
  - `src/core/tts/voice_designer.py`
  - `src/core/tts/audio_preprocessor.py`
- 当前 `voice` 相关能力包括：
  - profile 列表与详情
  - 音色设计
  - 音色克隆
  - 参考片段分析
  - profile 试听
- 这些能力并不是所有 TTS 引擎都天然拥有，换引擎后也不保证能保留同样的数据结构与工作流。

## 功能定位

功能 10 是 TTS provider 级功能域。

它负责：

1. 管理系统中的 TTS 引擎注册与能力声明。
2. 定义所有 TTS 引擎共享的通用能力边界。
3. 挂接某些引擎专属的扩展能力。
4. 为功能 2、功能 4、功能 6 提供稳定的 TTS 引擎消费接口。

它不把“音色资产与音色生成”定义成全局一级功能，而是将其视为部分引擎的扩展能力。

## 与其他功能的关系

### 与功能 6 的关系

- 功能 6 负责 provider 参数 schema、默认值、`CapabilityDescriptor` 和 `ExecutionProfile` 规则。
- 功能 10 负责 TTS 类 provider 的业务能力边界与具体接入方式。
- 换句话说：
  - 功能 6 负责“参数长什么样”
  - 功能 10 负责“这个 TTS 引擎实际上能做什么”

### 与功能 5 的关系

- 功能 5 负责本地模型、运行资源、可执行性检查。
- 功能 10 负责告诉功能 5：某个 TTS 引擎运行时依赖哪些资源。

### 与功能 4 的关系

- 功能 4 的 `tool.tts` 只是一种工具任务入口。
- 真正的 TTS 执行业务逻辑与引擎分发归属功能 10。

### 与功能 2 的关系

- 功能 2 中的 `tts_profile` 不应直接面向具体类和私有实现。
- 功能 2 只消费功能 10 暴露的标准 TTS 能力。

## 边界

### 本功能负责

- TTS 引擎注册与能力声明
- TTS 通用能力定义
- TTS 执行器或 provider adapter 管理
- 引擎专属扩展能力挂接
- TTS 引擎级 profile / clone / preview / analysis 的归属判断

### 本功能不负责

- 不负责全局 provider 参数 schema 定义，这属于功能 6
- 不负责模型 ready 状态和运行时目录检查，这属于功能 5
- 不负责工具任务排队，这属于功能 3
- 不负责完整流水线编排，这属于功能 2
- 不负责将所有音色能力包装为全局通用 UI 能力

## 核心原则

### 1. TTS 通用能力和扩展能力必须分开

V1 需要明确区分：

- **通用能力**
  - 文本转语音
  - voice / speaker 选择
  - speed
  - volume
  - output format

- **扩展能力**
  - voice profile
  - voice clone
  - reference audio analysis
  - style / emotion control
  - preview by profile

只有通用能力才允许作为跨引擎稳定契约。

### 2. 音色功能不是全局主能力

V1 需要明确：

- “音色资产”
- “音色克隆”
- “参考音频建模”
- “音色设计”

这些都不是所有 TTS 引擎必须拥有的能力。

因此：

- 它们不能作为全局一级功能写死
- 它们只能作为某些 TTS 引擎的扩展能力声明存在

### 3. 引擎能力必须显式声明

每个 TTS 引擎都必须给出能力描述，而不能靠页面或执行器猜。

建议至少声明：

- 是否支持 `voice list`
- 是否支持 `speaker`
- 是否支持 `profile`
- 是否支持 `clone`
- 是否支持 `reference_audio`
- 是否支持 `preview`
- 是否支持 `emotion`
- 是否支持 `style`

## V1 需要实现的功能

### 1. TTS 引擎注册表

V1 需要建立独立于通用 provider schema 的 TTS 引擎注册表。

建议至少定义：

- `engine_id`
- `display_name`
- `kind`
- `available`
- `capabilities`
- `supported_models`
- `default_voice_mode`

其中 `kind` 至少区分：

- `local`
- `cloud`
- `hybrid`

### 2. TTS 通用执行接口

V1 需要统一 TTS 执行入口，不再让每个调用方各自理解底层实现。

统一接口至少应覆盖：

- 文本输入
- voice / speaker 选择
- speed
- 输出路径或输出格式

不要求所有引擎支持完全相同的扩展参数，但要求通用能力有稳定接口。

### 3. TTS 引擎扩展能力声明

V1 需要允许每个引擎额外挂接扩展能力。

例如某个引擎可能支持：

- `profile_management`
- `voice_clone`
- `segment_analysis`
- `profile_preview`

而另一个引擎可能只支持：

- `voice_selection`

这部分必须显式暴露给功能 6 和前端，而不是硬编码在 Voice Lab 页面里。

### 4. 引擎扩展资源对象

对于支持 profile / clone 的引擎，V1 可以保留扩展资源对象，但要明确它们是“引擎附带对象”。

例如：

- `TtsEngineProfile`
- `TtsEngineCloneJob`
- `TtsEnginePreviewResult`

注意：

- 这些不是全局统一领域主对象
- 它们属于具体引擎扩展能力

### 5. TTS 预览与测试能力

V1 允许定义轻量的 TTS 预览和测试能力：

- 文本试听
- profile 试听
- 基础引擎可用性测试

但这些能力的可用范围必须跟随引擎 capability，而不是默认所有引擎都有。

## API 设计

### 通用 TTS API

- `POST /api/v1/tts/synthesize`
- `GET /api/v1/tts/engines`
- `GET /api/v1/tts/engines/{engine_id}`

用途：

- 提供 TTS 通用合成与引擎能力查询

### 扩展能力 API

以下接口只应理解为“某些引擎的扩展能力入口”，不是全局强契约：

- `GET /api/v1/voice/profiles`
- `GET /api/v1/voice/profiles/{profile_id}`
- `POST /api/v1/voice/design`
- `POST /api/v1/voice/clone`
- `POST /api/v1/voice/analyze-segments`
- `POST /api/v1/voice/profiles/{profile_id}/preview`

说明：

- 当前可以兼容保留 `voice` 路由
- 但文档上必须明确：这些是 TTS 引擎扩展能力，不是所有引擎都支持的全局功能

## 中间层设计

### `TtsEngineRegistryService`

职责：

- 管理 TTS 引擎注册表
- 提供引擎能力查询
- 为调用方暴露 TTS capability

### `TtsEngineExecutionService`

职责：

- 执行通用 TTS 合成
- 根据 `ExecutionProfile` 分发到正确引擎

### `TtsExtensionCapabilityService`

职责：

- 管理 profile / clone / preview / analysis 等扩展能力
- 判断某个引擎是否支持某项扩展能力

### `VoiceExtensionService`

职责：

- 作为当前仓库里 voice/profile 相关扩展逻辑的兼容收口层
- 逐步从“独立功能页”迁移为“特定 TTS 引擎扩展能力”

## 与当前实现的关系

### 可以保留的思路

- `TtsService` 作为稳定通用 TTS 入口的方向
- `VoiceService` 作为扩展能力 facade 的方向
- `voice_profile`、`voice_designer`、`audio_preprocessor` 作为扩展实现基础
- `ModelManager` 中按 `tts` category 管理 provider 的思路

### 必须重组或迁移的部分

- 当前 `voice` 能力不能再被叙述成独立稳定主功能
- `Voice Lab` 页面不应主导产品功能边界
- pipeline 中的 `tts_engine`、`tts_voice`、`voice_profile_id` 等平铺字段后续应迁移到标准化 TTS profile
- `TtsService` 和 `VoiceService` 的边界需要进一步拆成“通用能力”和“扩展能力”

### 明确不继承的历史包袱

- 不继承“所有 TTS 引擎都有 profile / clone”的假设
- 不继承“音色实验室天然是一级产品域”的假设
- 不继承“换引擎后扩展能力还能保持同样对象模型”的假设

## V1 内必须落地

1. 明确 TTS 通用能力边界
2. 建立 TTS 引擎能力声明
3. 明确 `voice` 路由属于 TTS 扩展能力
4. 将音色相关能力降级为引擎附带扩展，而不是全局主能力

## V1 内暂不落地

1. 不在这一轮统一所有引擎的 profile 数据结构
2. 不在这一轮做跨引擎 profile 迁移
3. 不在这一轮做复杂 Voice Lab 工作流重构
4. 不在这一轮保证所有扩展能力在任意 TTS 引擎上有等价实现

## 一句话结论

功能 10 可以正式定义为：

> TTS 引擎管理与扩展能力管理 = 统一管理 TTS 引擎的通用合成能力与引擎专属扩展能力，并明确音色、克隆、试听等只是部分引擎的附带能力，而不是全局稳定主功能。
