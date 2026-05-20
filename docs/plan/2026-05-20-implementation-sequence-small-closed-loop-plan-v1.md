# AsmrHelper 按模块小闭环实施计划 V1

## 目标

- 给出一份可以直接执行的重构顺序，而不是继续停留在功能抽象层。
- 采用“按模块小闭环”的方式推进，避免全项目先做完 backend/core 再统一迁 application/service 的高返工风险。
- 每个阶段都要求形成最小可运行闭环：
  - 后端能力
  - 中间层承接
  - 兼容入口

## 执行原则

### 1. 模块内前后连做

每个模块都按下面顺序推进：

1. 收口该模块的领域模型或引擎能力
2. 补齐该模块的 application/service 承接层
3. 保留或改造兼容 route
4. 跑通最小调用链

### 2. 项目级按依赖顺序推进

不按页面推进，不按“先全 backend 再全 service”推进，而按依赖链推进。

### 3. 优先稳定契约，不优先改页面

前端和页面层后置，先把：

- 配置
- runtime
- session
- task
- subtitle asset
- artifact

这些稳定下来。

### 4. 每阶段必须有退出条件

每一阶段都要有明确“完成标准”，否则容易无限延长。

## 推荐总顺序

建议按 6 个阶段推进：

1. 底座主干阶段
2. 资产层阶段
3. 引擎能力域阶段
4. 执行壳层阶段
5. 结果消费层阶段
6. 兼容清理阶段

---

## 阶段 1：底座主干

### 目标功能域

- 功能 6：配置与提供方接入管理
- 功能 5：模型与运行资源管理
- 功能 1：工作空间与输入管理
- 功能 3：统一任务生成与任务队列

### 为什么先做这一批

这一批决定后面所有模块的共同语言：

- `CapabilityDescriptor`
- `ExecutionProfile`
- `RuntimeBinding`
- `session`
- `task`

如果这一层不先稳，后面的 TTS / LLM / ASR 和 pipeline 仍会继续围绕旧参数结构生长。

### 推荐先动文件

- [src/config.py](/D:/WorkSpace/AsmrHelper/src/config.py)
- [src/app/services/resource_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/resource_service.py)
- [src/app/services/model_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/model_service.py)
- [src/app/services/task_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/task_service.py)
- [src/app/services/pipeline_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/pipeline_service.py)
- [src/api/http/routes/models.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/models.py)
- [src/api/http/routes/resources.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/resources.py)
- [src/api/http/routes/tasks.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/tasks.py)

### 本阶段产出

- 统一配置读取与脱敏输出
- capability 查询接口雏形
- runtime readiness 检查雏形
- session 生成雏形
- task spec 与 task queue 雏形

### 完成标准

- 配置层能输出统一 `CapabilityDescriptor`
- task 层能接受标准任务定义
- session 层能生成标准输入会话
- runtime 层能判断任务是否可运行

---

## 阶段 2：资产层

### 目标功能域

- 功能 7：字幕与文本资产管理
- 功能 8：结果资产与产物索引管理

### 为什么第二个做

这是最容易持续分裂的一层。

只要字幕资产和结果资产不先统一：

- pipeline 会自己定义结果
- tool 会自己定义结果
- 前端会自己拼结果

后面再收口会非常痛苦。

### 推荐先动文件

- [src/app/services/subtitle_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/subtitle_service.py)
- [src/app/services/script_subtitle_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/script_subtitle_service.py)
- [src/core/subtitle_generator.py](/D:/WorkSpace/AsmrHelper/src/core/subtitle_generator.py)
- [src/core/script_to_subtitle/pipeline.py](/D:/WorkSpace/AsmrHelper/src/core/script_to_subtitle/pipeline.py)
- [src/core/script_to_subtitle/tool.py](/D:/WorkSpace/AsmrHelper/src/core/script_to_subtitle/tool.py)
- [src/core/translate/subtitle_cleaner.py](/D:/WorkSpace/AsmrHelper/src/core/translate/subtitle_cleaner.py)
- [src/core/pipeline/artifact_collector.py](/D:/WorkSpace/AsmrHelper/src/core/pipeline/artifact_collector.py)
- [src/api/http/routes/subtitles.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/subtitles.py)

### 本阶段产出

- `SubtitleDocument` / `SubtitleCue` 等稳定字幕资产
- 字幕 parse / normalize / export 主路径
- 统一 `Artifact` / `ArtifactSet`
- 主产物和缺失语义规则

### 完成标准

- 字幕解析、清洗、导出不再散落多处
- 任务结果能统一返回结构化 artifact
- 脚本转字幕的领域逻辑从工具壳中抽出

---

## 阶段 3：引擎能力域

### 目标功能域

- 功能 10：TTS 引擎管理与扩展能力管理
- 功能 11：LLM 能力管理与衍生操作管理
- 功能 12：ASR 引擎管理与扩展能力管理

### 为什么第三个做

到这个阶段：

- 配置层已经能表达 capability 和 profile
- 资产层已经能承接字幕和结果

此时再收口引擎能力域，才能真正摆脱当前单引擎和平铺参数模型。

### 推荐先动文件

- [src/app/services/tts_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/tts_service.py)
- [src/app/services/voice_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/voice_service.py)
- [src/app/services/translation_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/translation_service.py)
- [src/app/services/asr_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/asr_service.py)
- [src/core/tts](/D:/WorkSpace/AsmrHelper/src/core/tts)
- [src/core/translate](/D:/WorkSpace/AsmrHelper/src/core/translate)
- [src/core/asr](/D:/WorkSpace/AsmrHelper/src/core/asr)
- [src/api/http/routes/tts.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/tts.py)
- [src/api/http/routes/voice.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/voice.py)
- [src/api/http/routes/translation.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/translation.py)
- [src/api/http/routes/asr.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/asr.py)

### 本阶段产出

- TTS / LLM / ASR registry service 雏形
- 统一执行 service 雏形
- 扩展能力声明雏形
- 当前 facade 降级为兼容层

### 完成标准

- `tts`、`llm`、`asr` 能力边界不再由旧 route 或旧工具页定义
- `/voice/*` 明确为 TTS 扩展能力入口
- `/translation/*` 明确为 LLM 衍生操作兼容入口
- 当前 ASR 实现被视为一个引擎，而不是产品边界

---

## 阶段 4：执行壳层

### 目标功能域

- 功能 2：单任务音频汉化流水线编排执行器
- 功能 4：单步工具执行体系

### 为什么第四个做

执行壳层高度依赖前面三层：

- 底座主干
- 资产层
- 引擎能力域

如果太早做，最终还会被迫回头改参数模型和能力依赖。

### 推荐先动文件

- [src/app/services/pipeline_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/pipeline_service.py)
- [src/app/services/audio_tool_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/audio_tool_service.py)
- [src/app/services/batch_pipeline_service.py](/D:/WorkSpace/AsmrHelper/src/app/services/batch_pipeline_service.py)
- [src/core/pipeline](/D:/WorkSpace/AsmrHelper/src/core/pipeline)
- [src/api/http/routes/pipeline.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/pipeline.py)
- [src/api/http/routes/tools.py](/D:/WorkSpace/AsmrHelper/src/api/http/routes/tools.py)

### 本阶段产出

- `PipelineTaskOrchestrator`
- `PipelineStepPlanner`
- `ToolRegistry`
- 各工具执行器雏形
- `tool-runs` 主入口雏形

### 完成标准

- pipeline 改为 task 驱动，而不是路径驱动
- tool 改为执行器驱动，而不是大杂烩 service
- batch 不再直接循环调 pipeline，而是生成任务

---

## 阶段 5：结果消费层

### 目标功能域

- 功能 9：结果预览、浏览与人工校对

### 为什么第五个做

结果消费层应该晚于结果资产层和执行壳层。

否则页面很容易继续反向定义结果模型。

### 推荐先动文件

- 结果预览相关前端组件
- 任务结果展示相关前端组件
- 轻量 review 状态承接逻辑

当前仓库里优先关注：

- `desktop/src/pages/Tasks.tsx`
- `desktop/src/pages/Workbench.tsx`
- 底部播放器相关组件

### 本阶段产出

- 轻量预览包展示
- 主产物优先展示
- 次级结果查看
- `accepted / needs_review / needs_rework`

### 完成标准

- 用户能查看和试听主结果
- 失败任务也能看到已产出的部分内容
- 轻量人工确认可用

---

## 阶段 6：兼容清理

### 目标

- 清理旧平铺字段依赖
- 降级旧 route 和旧 facade 的地位
- 把旧页面逻辑彻底变成消费层

### 重点对象

- `/tools/*`
- `/translation/*`
- `/voice/*`
- 当前平铺字段风格的 pipeline request
- 前端本地 task 视图状态

### 完成标准

- 主路径已经全面使用新契约
- 旧入口只作为兼容层保留
- 页面层不再定义业务边界

---

## 第一批推荐切片

如果你希望尽快动工，我建议第一批不要贪多，先做这 4 个切片：

1. 配置与 capability descriptor
   - 目标：让参数模型真正统一

2. session + task spec
   - 目标：让系统从路径驱动改成任务驱动

3. subtitle asset + artifact set
   - 目标：让中间资产和结果资产不再继续分裂

4. TTS / LLM / ASR registry 雏形
   - 目标：让引擎能力不再绑定当前单实现

## 当前最不推荐的启动方式

为了避免返工，当前最不推荐直接这样开始：

- 直接重写前端页面
- 直接继续扩展 `PipelineService`
- 直接把 `audio_tool_service.py` 做得更大
- 先做完整播放器或 VoiceLab
- 先做复杂人工校对

## 一句话结论

当前最推荐的执行顺序是：

> 先做底座主干，再做字幕与结果资产，再做 TTS / LLM / ASR 引擎能力域，最后重构流水线与工具执行壳层，并以小闭环方式逐阶段推进。
