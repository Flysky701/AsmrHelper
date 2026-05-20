# 切片 01：配置与 Capability Descriptor 落地计划 V1

## 目标

- 将当前基于 [src/config.py](/D:/WorkSpace/AsmrHelper/src/config.py) 的单体配置读写逻辑，收口成新架构下的配置与能力描述底座。
- 为后续 `session / task / pipeline / tool / engine` 全部模块提供统一的参数定义来源。
- 在不一次性重写全部配置体系的前提下，先形成一个最小闭环：
  - 统一配置模型
  - 配置读取与脱敏输出
  - capability descriptor 查询
  - execution profile 生成雏形

## 切片定位

这是整个阶段 1 的第一个切片。

它不负责：

- 任务系统本身
- session 本身
- runtime readiness 本身
- TTS / LLM / ASR 引擎的完整实现

它只负责把这些系统未来共同依赖的“参数语言”先建起来。

## 当前问题

当前 [src/config.py](/D:/WorkSpace/AsmrHelper/src/config.py) 的问题已经比较明确：

1. 同时承担读取、默认值、环境变量覆盖、保存、校验。
2. 只管理扁平配置事实，没有正式输出 `CapabilityDescriptor`。
3. 还在使用：
   - `tts.engine`
   - `api.provider`
   - `processing.asr_model`
   这种面向当前实现的旧字段语义。
4. 没有“标准化 execution profile”概念。
5. 没有统一脱敏视图，后续 settings API 不够稳定。

## 本切片范围

### 本切片要完成

1. 定义统一配置 schema 的 Python 侧承接层
2. 拆出配置读取与覆盖逻辑
3. 增加 capability descriptor 注册与查询能力
4. 增加 execution profile builder 雏形
5. 提供 settings / capabilities 的最小 API 雏形
6. 保留旧 `config` 用法兼容，不立刻打断现有调用链

### 本切片明确不做

1. 不在这一轮重写全部前端 Settings 页面
2. 不在这一轮完成所有 provider 的完整 capability
3. 不在这一轮让 pipeline / tool 全部切到新 profile
4. 不在这一轮完成 runtime binding
5. 不在这一轮移除旧 `config.get(...)` 用法

## 目标产物

本切片完成后，系统至少应该新增并稳定以下对象：

### 1. `SettingsService`

负责：

- 读取配置
- 保存配置
- 输出脱敏视图
- 基础 schema 校验

### 2. `ConfigOverlayService`

负责：

- 合并 built-in defaults
- 合并 config file
- 合并 env overrides
- 为后续 runtime overrides 预留接口

### 3. `CapabilityDescriptorService`

负责：

- 注册 capability descriptor
- 按 category/provider 查询 descriptor
- 给前端和任务系统提供参数描述

### 4. `ExecutionProfileBuilder`

负责：

- 从默认值 + 用户输入 + capability descriptor 生成标准 execution profile
- 当前先支持基础结构，不要求一次覆盖所有 provider 特性

## 推荐文件改动范围

### 第一批核心文件

- [src/config.py](/D:/WorkSpace/AsmrHelper/src/config.py)
- [src/app/services/__init__.py](/D:/WorkSpace/AsmrHelper/src/app/services/__init__.py)
- [src/api/http/dependencies.py](/D:/WorkSpace/AsmrHelper/src/api/http/dependencies.py)

### 建议新增文件

- `src/app/services/settings_service.py`
- `src/app/services/capability_descriptor_service.py`
- `src/app/services/execution_profile_builder.py`

### 建议新增 route / schema 文件

- `src/api/http/routes/settings.py`
- `src/api/http/schemas/settings.py`
- `src/api/http/routes/capabilities.py`
- `src/api/http/schemas/capabilities.py`

说明：

- 本切片先不要求大改现有 `models.py / resources.py / tasks.py`
- 先把配置底座本身建出来

## Capability Descriptor 第一批覆盖范围

本切片不追求把所有能力描述一次做满。

建议第一批只覆盖 4 个 category：

1. `tts`
2. `llm`
3. `asr`
4. `separator`

每个 category 第一批只需要提供：

- provider 标识
- supported models
- common option schema
- provider option schema
- 基础 supports 标志

### 第一批 provider 建议

#### `tts`

- `edge`
- `qwen3`

#### `llm`

- `deepseek`
- `openai`

#### `asr`

- `faster_whisper`

#### `separator`

- `htdemucs`
- `mdx`

## Execution Profile 第一批范围

本切片只要求能生成最基础 profile 结构：

```json
{
  "category": "tts",
  "provider": "edge",
  "model": "default",
  "common_options": {
    "voice": "zh-CN-XiaoxiaoNeural",
    "speed": 1.0
  },
  "provider_options": {}
}
```

第一批不要求：

- 所有 provider 的全部私有参数都完善
- pipeline / tool 已全部切换到 profile 驱动

第一批只要求：

- builder 能正确构出 profile
- query API 能把 descriptor 暴露出来

## API 最小落地范围

本切片建议先落以下接口：

### `GET /api/v1/settings`

返回：

- 当前生效配置的脱敏视图

### `PUT /api/v1/settings`

返回：

- 更新后的脱敏配置视图

### `POST /api/v1/settings/validate`

返回：

- 基础校验结果

### `GET /api/v1/capabilities`

返回：

- 所有已注册 capability descriptor

### `GET /api/v1/capabilities/{category}`

返回：

- 某一类能力的 descriptor 列表

说明：

- `test-provider` 可以在本切片里先只预留，不强制首轮落地

## 实施步骤

### Step 1：从 `src/config.py` 提炼默认值与 overlay 逻辑

目标：

- 先不打断旧 `Config`
- 抽出更稳定的 overlay 逻辑

完成后应有：

- built-in defaults 统一来源
- env overrides 统一来源
- file merge 统一入口

### Step 2：新增 `SettingsService`

目标：

- 给 API 层一个稳定 service，而不是直接暴露 `Config`

完成后应有：

- 读取配置
- 保存配置
- 脱敏输出
- 基础 validate

### Step 3：新增 `CapabilityDescriptorService`

目标：

- 先用代码注册方式提供 descriptor

完成后应有：

- 按 category 返回 descriptors
- 按 provider 返回 descriptor

### Step 4：新增 `ExecutionProfileBuilder`

目标：

- 能从默认配置和显式输入生成标准 profile

完成后应有：

- `tts` / `llm` / `asr` / `separator` 的基础 builder

### Step 5：补 settings / capabilities 路由

目标：

- 把新底座真正暴露成可消费接口

完成后应有：

- 新 route
- 新 schema
- dependency wiring

### Step 6：补兼容层说明

目标：

- 保持当前 `src/config.py` 老调用仍可继续工作
- 但新路径从 service 层开始走

## 完成标准

本切片完成后，必须满足以下标准：

1. 系统能通过 API 返回脱敏后的 settings
2. 系统能通过 API 返回 capability descriptors
3. `CapabilityDescriptorService` 能覆盖 `tts / llm / asr / separator` 的第一批 provider
4. `ExecutionProfileBuilder` 能生成基础 profile
5. 旧 `Config` 调用链不被立即打断

## 风险与控制

### 风险 1：过早追求全量 schema

控制：

- 第一批只做最基础 category 与 provider

### 风险 2：把 capability descriptor 写死成当前实现细节

控制：

- descriptor 只描述能力和参数，不直接嵌入页面语义

### 风险 3：一次性替换旧配置调用

控制：

- `src/config.py` 本轮先兼容保留
- 新 service 先并存

## 切片完成后的直接下一步

这个切片做完后，最自然的下一步就是：

- 切片 02：`session + task spec`

因为一旦 capability descriptor 和 execution profile 能稳定输出，任务系统就能开始真正从“平铺参数”迁到“标准任务定义”。

## 一句话结论

切片 01 的本质是：

> 先把“系统如何描述能力、配置和执行参数”这门统一语言建起来，再让后续 session、task、pipeline 和 engine 能力域都基于它继续生长。
