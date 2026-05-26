# 切片 02-04 执行计划 V1

## 前置状态

切片 01（配置与 Capability Descriptor）已完成落地：

- `SettingsService` — 配置读写与脱敏输出
- `CapabilityDescriptorService` — 4 类能力描述注册（tts/llm/asr/separator）
- `ExecutionProfileBuilder` — 基础 execution profile 生成
- `build_effective_config` — 配置合并模式
- 路由 `settings.py`、`capabilities.py` 已注册

本计划覆盖阶段 1 剩余的 3 个切片，目标是完成底座主干。

---

## 切片 02：会话 → 输入资产 → 任务规格闭环

### 目标

让系统从"路径驱动"迁移到"会话 + 任务驱动"。验证 `WorkspaceService → InputCatalogService → SessionService → TaskService` 调用链端到端可用。

### 当前状态

| 组件 | 行数 | 状态 |
|------|------|------|
| `WorkspaceService` | 47 | 已实现，缺测试 |
| `InputCatalogService` | 134 | 已实现，缺测试 |
| `SessionService` | 113 | 已实现，缺测试 |
| `TaskService` | 188 | 已实现，内存状态表，缺并发控制 |
| 路由 `workspaces.py` | 25 | 骨架已有 |
| 路由 `sessions.py` | 38 | 骨架已有 |
| 路由 `inputs.py` | 56 | 骨架已有 |
| 路由 `tasks.py` | 169 | 已实现 |

### 需要完成的工作

#### Step 1：补 DTO 与契约验证

- 确认 `WorkspaceContext`、`InputAsset`、`ProcessingSession`、`TaskSpec` 字段完整性
- 确认 `TaskSpec` 能承载 `task_type`、`session_id`、`execution_profile`、`priority`
- 在 `src/app/dto/__init__.py` 中补齐缺失字段

#### Step 2：升级 TaskService 状态机

当前 `TaskService` 是简单的内存字典，需要补强：

- 任务状态机：`pending → running → completed / failed / cancelled`
- 并发控制：最大并行任务数
- 任务取消支持
- 任务进度回调接口

改动文件：
- `src/app/services/task_service.py`

#### Step 3：验证端到端调用链

编写集成测试，覆盖以下链路：

```
POST /workspaces/resolve          → 获取 WorkspaceContext
POST /inputs/inspect              → 获取 InputAsset 列表
POST /sessions                    → 创建 ProcessingSession
POST /tasks                       → 创建 TaskSpec（关联 session_id）
GET  /tasks/{id}                  → 查询任务状态
```

新增测试文件：
- `tests/test_session_task_chain.py`

#### Step 4：路由层补全

确认 `workspaces.py`、`sessions.py`、`inputs.py` 路由的请求/响应 schema 完整。

改动文件：
- `src/api/http/routes/workspaces.py`
- `src/api/http/routes/sessions.py`
- `src/api/http/routes/inputs.py`
- `src/api/http/schemas/sessions.py`
- `src/api/http/schemas/inputs.py`

### 完成标准

- [ ] `WorkspaceService.resolve()` 返回完整 `WorkspaceContext`
- [ ] `InputCatalogService.inspect_paths()` 正确识别音频/字幕/脚本类型
- [ ] `SessionService.create_session()` 生成有效 `ProcessingSession`
- [ ] `TaskService` 支持创建、查询、取消任务
- [ ] 集成测试覆盖完整调用链
- [ ] 旧 `PipelineService` 直接调用仍不受影响

---

## 切片 03：字幕资产与结果产物统一

### 目标

将字幕解析/导出和结果产物索引从各执行器中抽出，建立统一的资产模型。避免 pipeline、tool、前端各自维护一套结果结构。

### 当前状态

| 组件 | 行数 | 状态 |
|------|------|------|
| `SubtitleService` | 294 | 已实现，覆盖解析/导出 |
| `ScriptSubtitleService` | 181 | 已实现，覆盖脚本转字幕 |
| `ArtifactService` | 143 | 已实现，缺路由 |
| `subtitle_generator.py` (core) | 724 | 底层实现完整 |
| `script_to_subtitle/` (core) | — | 底层实现完整 |
| 路由 `subtitles.py` | 157 | 已实现 |
| 路由 `artifacts` | — | 不存在 |

### 需要完成的工作

#### Step 1：稳定字幕资产 DTO

确认 `SubtitleDocument`、`SubtitleSegment`、`SubtitleAsset` 字段与计划一致：

- `SubtitleDocument`：segments 列表、语言、格式、来源
- `SubtitleSegment`：index、start_ms、end_ms、text、language
- `SubtitleAsset`：document + 文件路径 + 格式标识

改动文件：
- `src/app/dto/__init__.py`

#### Step 2：统一 Artifact 模型

确认 `ArtifactRecord`、`ArtifactSet` 能覆盖以下场景：

- 混音成品、字幕文件、TTS 音频、vocals、transcript、分析结果
- 主产物判定规则
- 缺失语义（任务成功但某产物未生成）

改动文件：
- `src/app/dto/__init__.py`
- `src/app/services/artifact_service.py`

#### Step 3：Artifact 路由

新增 `src/api/http/routes/artifacts.py` 和对应 schema：

- `GET /artifacts/{task_id}` — 查询任务的产物集
- `GET /artifacts/{task_id}/{artifact_type}` — 获取特定产物

新增文件：
- `src/api/http/routes/artifacts.py`
- `src/api/http/schemas/artifacts.py`

#### Step 4：字幕服务与任务系统对接

让 `SubtitleService` 能消费 `TaskSpec` 中的 session 信息，而不是直接接收裸路径。

改动文件：
- `src/app/services/subtitle_service.py`

#### Step 5：补测试

新增测试覆盖：

- 字幕解析 → 标准化 → 导出闭环
- Artifact 创建 → 查询 → 主产物判定
- 脚本转字幕通过 session 驱动

新增测试文件：
- `tests/test_subtitle_asset.py`
- `tests/test_artifact_service.py`

### 完成标准

- [ ] `SubtitleDocument` 成为字幕唯一标准模型
- [ ] `ArtifactSet` 能统一表达所有任务类型的结果
- [ ] 主产物判定规则有明确实现
- [ ] 新增 `artifacts` 路由可查询
- [ ] 字幕服务不再直接接收裸路径，改为接收 session 上下文

---

## 切片 04：TTS / LLM / ASR 引擎注册雏形

### 目标

将 TTS、LLM、ASR 从"单实现 service"升级为"引擎注册 + 统一执行"模式。让引擎能力不再绑定当前单一实现。

### 当前状态

| 组件 | 行数 | 状态 |
|------|------|------|
| `TtsService` | 54 | 薄 facade |
| `TtsEngineService` | 85 | 已有注册骨架 |
| `VoiceService` | 252 | 扩展能力已有 |
| `LlmCapabilityService` | 94 | 已有注册骨架 |
| `TranslationService` | ~60 | 薄 facade |
| `AsrService` | ~60 | 薄 facade |
| `AsrEngineService` | 96 | 已有注册骨架 |
| `CapabilityDescriptorService` | 201 | 已注册 tts/llm/asr/separator |

### 需要完成的工作

#### Step 1：TTS 引擎注册

将 `TtsEngineService` 升级为真正的引擎注册表：

- 注册 `edge` 和 `qwen3` 引擎
- 每个引擎声明自己的 `CapabilityDescriptor`
- 提供 `synthesize(text, profile) → audio` 统一接口
- `VoiceService` 作为扩展能力层，仅在引擎支持时可用

改动文件：
- `src/app/services/tts_engine_service.py`
- `src/app/services/tts_service.py`
- `src/app/services/voice_service.py`

#### Step 2：ASR 引擎注册

将 `AsrEngineService` 升级：

- 注册 `faster_whisper` 引擎
- 提供 `transcribe(audio, profile) → segments` 统一接口
- 后续新引擎只需实现接口即可接入

改动文件：
- `src/app/services/asr_engine_service.py`
- `src/app/services/asr_service.py`

#### Step 3：LLM 能力收口

将 `LlmCapabilityService` 升级：

- 注册 `deepseek` 和 `openai` provider
- 统一 `chat(messages, profile) → response` 接口
- `TranslationService` 改为消费 LLM 能力，而非独立实现
- 为后续脚本清洗、对齐、重写预留衍生操作注册点

改动文件：
- `src/app/services/llm_capability_service.py`
- `src/app/services/translation_service.py`

#### Step 4：引擎路由补全

确认以下路由能正确暴露引擎能力：

- `tts.py` — 合成接口，消费 `ExecutionProfile`
- `asr.py` — 识别接口，消费 `ExecutionProfile`
- `llm.py` — 对话接口，消费 `ExecutionProfile`
- `voice.py` — TTS 扩展能力（保持兼容）

改动文件：
- `src/api/http/routes/tts.py`
- `src/api/http/routes/asr.py`
- `src/api/http/routes/llm.py`

#### Step 5：补测试

- TTS 引擎注册与切换测试
- ASR 引擎注册与切换测试
- LLM provider 注册与调用测试
- ExecutionProfile 驱动引擎调用的集成测试

新增测试文件：
- `tests/test_engine_registry.py`

### 完成标准

- [ ] TTS 能通过 `ExecutionProfile` 选择引擎和参数
- [ ] ASR 能通过 `ExecutionProfile` 选择引擎和参数
- [ ] LLM 能通过 `ExecutionProfile` 选择 provider 和参数
- [ ] 引擎注册表支持动态查询已注册引擎
- [ ] 旧 `tts_service.synthesize()` 调用仍兼容
- [ ] 旧 `asr_service.transcribe()` 调用仍兼容

---

## 总体依赖关系

```
切片 01（已完成）
  └─ 切片 02（会话 + 任务）
       └─ 切片 03（字幕资产 + 结果产物）
            └─ 切片 04（引擎注册）
```

切片 02 和 03 有轻度依赖（任务系统需要能引用资产），但 03 的字幕 DTO 部分可以与 02 并行推进。

切片 04 依赖 02（引擎调用需要通过任务系统发起）和 03（引擎结果需要统一为 artifact）。

## 执行节奏建议

每个切片按以下节奏推进：

1. **DTO / 契约确认**（0.5 天）— 确认数据结构
2. **Service 实现**（1-2 天）— 核心逻辑
3. **路由补全**（0.5 天）— API 暴露
4. **测试验证**（1 天）— 单元 + 集成
5. **兼容性确认**（0.5 天）— 旧调用不受影响

预计每个切片 3-5 天，总计 2-3 周完成阶段 1 底座主干。

## 一句话结论

> 切片 02 建立会话与任务驱动，切片 03 统一资产模型，切片 04 收口引擎注册，三步完成后阶段 1 底座主干闭合，后续 TTS/LLM/ASR 和 pipeline/tool 都基于统一语言继续生长。
