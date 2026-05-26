# AsmrHelper Phase 2 里程碑状态盘点 V1

## 文档定位

本文档是 `refactor/re-design` 分支在 2026-05-21 的正式里程碑记录。
工作区干净，无未提交改动，代码状态为可盘点的稳定截面。

## 一、仓库与文档状态

### 仓库状态

- 当前分支：`refactor/re-design`
- 工作区：干净，无未提交改动

### 文档状态

规划文档体系已完整建立：

- 功能域文档：功能 1-12（定义基线）
- 总览文档：功能架构、统一 API、service 映射（参考基线）
- 实施文档：Phase 2 legacy core 替换计划（当前活跃执行文档）

已归档文档（`docs/plan/archived/`）：

- Phase 1 实施顺序计划
- 切片 01 配置与 Capability Descriptor 实施计划
- 切片 02-04 执行计划
- 代码迁移清单 V1
- Git 恢复审计计划
- 脚本字幕测试稳定性修复计划
- Core 架构差异复核与目标结构 V1

归档原因：Phase 1 已完成，这些文档的结论已被当前代码状态和 Phase 2 计划取代。

## 二、功能域进度总表

| 功能 | 名称 | 状态 | 关键判断 |
|------|------|------|----------|
| 1 | 工作空间与输入管理 | ✅ 基本落地 | workspaces/inputs/sessions 主接口已有，WorkspaceService/InputCatalogService/SessionService 已实现 |
| 2 | 单任务流水线编排执行器 | 🔧 进行中 | pipeline-runs/task-driven 路径在，但底层仍有 legacy core.pipeline 依赖。当前最大未完成项 |
| 3 | 统一任务生成与任务队列 | ✅ 基本落地 | tasks/batch/retry/task-queue 已有，轻量实现可用 |
| 4 | 单步工具执行体系 | ✅ 已接入主干 | tool-runs 已在，工具任务进统一任务体系。audio_tool_service 仍有瘦身空间 |
| 5 | 模型与运行资源管理 | ✅ 大体落地 | runtime/resources/capabilities/check-task-readiness 已有 |
| 6 | 配置与提供方接入管理 | ✅ 基本落地 | settings/effective/validate/test-provider/capabilities 都在 |
| 7 | 字幕与文本资产管理 | 🔧 已成形，继续归并 | subtitles 新分区完整（loader/parser/cleaner/normalizer/exporter），旧 translate/script_to_subtitle 待归并 |
| 8 | 结果资产与产物索引管理 | ✅ 轻量可用 | artifact 索引、by-task 查询已在 |
| 9 | 结果预览、浏览与人工校对 | ✅ 轻量方案落地 | preview/review-status/review-note 已有 |
| 10 | TTS 引擎管理与扩展能力管理 | 🔧 主干落地，过渡中 | engines/tts registry+service 已在，旧 tts 包和 Qwen3 逻辑待整理 |
| 11 | LLM 能力管理与衍生操作管理 | 🔧 主干落地，收口中 | engines/llm registry+service 已在，LlmOperationRuntime 开始统一入口 |
| 12 | ASR 引擎管理与扩展能力管理 | ✅ 主干落地 | engines/asr registry+service 已在，比 TTS/LLM 更稳定 |

## 三、Core 新分区落地确认

以下新分区已在 `src/core/` 中建立并有实质内容：

```
src/core/
├── sessions/        ← 功能 1（workspace/catalog/models/service）
├── tasks/           ← 功能 3（models/service）
├── artifacts/       ← 功能 8（models/service）
├── runtime/         ← 功能 5（models/service）
├── subtitles/       ← 功能 7（loader/parser/cleaner/normalizer/exporter/models/service）
├── engines/
│   ├── tts/         ← 功能 10（registry/service）
│   ├── llm/         ← 功能 11（registry/service）
│   ├── asr/         ← 功能 12（registry/service）
│   └── separator/   ← （registry/service）
├── orchestration/
│   ├── pipeline/    ← 功能 2（planner/result_mapper/models/service）
│   └── tools/       ← 功能 4（catalog）
```

## 四、仍存在的旧模块（Phase 2 替换目标）

```
src/core/
├── pipeline/              ← 旧 pipeline 主实现（step_executor/path_planner/artifact_collector 等）
├── model_manager.py       ← 旧集中式引擎管理
├── translate/             ← 旧 LLM + 字幕混合逻辑
├── script_to_subtitle/    ← 旧独立脚本转字幕流程
├── subtitle_generator.py  ← 旧字幕生成
├── script_processor.py    ← 旧脚本文本处理
├── tts/                   ← 旧 TTS 实现（待重挂到 engines/tts）
├── asr/                   ← 旧 ASR 实现（待重挂到 engines/asr）
├── vocal_separator/       ← 旧分离器实现（待重挂到 engines/separator）
└── gpu_manager.py         ← 旧 GPU 管理
```

## 五、Phase 2 子阶段进度

### Phase 2A：Pipeline 主路径替换

**状态：进行中，主干已切开**

已完成：
- `core/orchestration/pipeline/` 建立（planner/result_mapper/models/service）
- ExecutionPlan 概念引入
- forced_active_steps 支持
- orchestration 结果归一
- step executor 优先走新 engines runtime

未完成：
- 彻底摆脱旧 `core/pipeline` 主执行逻辑
- `PipelineService` 完全不依赖旧 `PipelineConfig`
- `LegacyPipelineOrchestrator` 降级为纯兼容适配器

### Phase 2B：ModelManager 拆解

**状态：进行中**

已完成：
- tts/llm/asr/separator 各自 registry 已建立
- 多处运行时入口已优先走 registry
- unload 兼容语义已修正

未完成：
- ModelManager 彻底退为兼容层
- GUI/旧路径对它的剩余依赖清理
- 新 service 全面停止依赖 ModelManager

### Phase 2C：字幕与文本旧逻辑归并

**状态：进行中**

已完成：
- `core/subtitles/` 完整建立（loader/exporter/bilingualize 主线）
- 部分应用层翻译入口改走新 LLM runtime

未完成：
- `translate/__init__.py` 中字幕加载/清洗逻辑迁出
- `script_to_subtitle/` 归并到 subtitles + engines/llm
- `subtitle_generator.py` 迁入 subtitles
- `script_processor.py` 迁入 subtitles

### Phase 2D：兼容层瘦身

**状态：未正式收尾**

当前 facade 比之前薄了，但还没到"纯 facade"状态：
- `pipeline_service.py` — 仍有较多旧逻辑拼装
- `audio_tool_service.py` — 仍有工具分支逻辑
- `translation_service.py` — 仍有旧翻译路径
- `tts_service.py` — 仍有旧引擎直调
- `asr_service.py` — 仍有旧引擎直调

## 六、总判断

> 功能架构、API 主线、core 新分区都已经建立完成。
> 当前正在做的是第二阶段的 legacy core 替换，其中 pipeline 主路径和旧字幕/文本逻辑归并是最主要的剩余工作。

项目已经不是"设计阶段"，也不是"只有适配层"。
准确定性为：**Phase 2 执行中期**。

## 七、推荐推进顺序

1. **继续 Phase 2A** — 把 step_executor 和旧 core.pipeline 的结果/阶段语义继续往 orchestration 收
2. **推进 Phase 2C** — 把 script_to_subtitle 及旧 translate 包里剩余的字幕/文本逻辑归并
3. **Phase 2B 收尾** — 让 ModelManager 明确退为兼容层
4. **Phase 2D 系统性瘦身** — app facade 收薄

## 八、本阶段暂不处理

- 不重做前端页面
- 不重做 GUI worker 全链路
- 不做任务持久化
- 不做分布式或跨进程队列
- 不重做音频算法本身

## 九、阶段完成标准

当下面 5 条满足时，Phase 2 可以视为完成：

1. `PipelineService` 新主路径不再依赖完整旧 `PipelineConfig`
2. `ModelManager` 不再是新 service 的主依赖入口
3. `core/subtitles` 成为字幕与脚本文本资产的主归属层
4. `core/engines/llm` 承接主要 LLM 衍生操作
5. app services 明显收薄，主要职责变成 facade
