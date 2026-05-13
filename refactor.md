# AsmrHelper 重构规划

## 一、文档定位
这份文档是项目的“现状对照 + 目标架构”主文档，用来回答四个问题：

1. 当前项目已经实现了什么。
2. 当前实现和目标架构之间还差什么。
3. 接下来应该优先重构哪些层，而不是一开始就全量重写。
4. Web、CLI、桌面端未来应该如何共享同一套后端能力。

这不是流程图，也不是任务清单，而是一份指导后续重构决策的架构说明。

---

## 二、当前判断
AsmrHelper 现在已经不是“功能还没长出来”的阶段，而是“功能已经不少，但边界不够清晰”的阶段。

当前项目已经具备这些核心能力：

- 音频主流程：人声分离、ASR、翻译、TTS、混音。

- 台本转字幕：PDF / TXT 清洗、ASR 对齐、LLM 对齐、字幕输出。

- 多入口：CLI、GUI、独立脚本。

- 模型资源：本地模型、云端模型、运行期加载、安装期下载。
意见，pytouch等大型依赖是否可以分版本下载（自动检查， 提供安装项）

当前真正的问题不是“缺某一个按钮”，而是：

- 多个入口各自拼接后端能力，复用边界不够清晰。
- GUI、CLI、脚本、流水线层之间有直接调用和参数散落。
- 后端能力还没有收束成统一的应用接口层。
- 未来如果要重做前端，现有后端没有天然适合接 Web / Desktop 的统一入口。

---

## 三、这次重构的核心方向
这次重构的主线不再是“先围绕某个界面或某条流程继续打补丁”，而是：

**先建立统一的应用 API 层，再让 Web、CLI、Desktop 都只通过这层调用后端能力。**

这意味着后续的架构目标不是：

- GUI 直接调 `core`
- CLI 再各写一套命令逻辑
- 脚本继续旁路调用底层模块

而是：

- 所有后端能力先收敛到统一的 Application API
- CLI 调 Application API
- Web 调 HTTP API，而 HTTP API 再调 Application API
- Desktop 也通过同一套 API 或同一套应用服务访问后端

一句话总结：

**重构重点不是先换前端，而是先把后端整理成值得被多个前端共享的一层。**

---

## 四、目标总体架构

### 4.1 分层结构
建议把项目长期收敛为四层：

```text
Frontend Layer
|- Web Frontend
|- Desktop Frontend
|- CLI UX

Transport / Adapter Layer
|- HTTP API
|- CLI Commands
|- Desktop Bridge

Application API Layer
|- PipelineService
|- SubtitleService
|- ModelService
|- ResourceService
|- TaskService

Core Domain Layer
|- ASR
|- Translate
|- TTS
|- VocalSeparator
|- ScriptToSubtitle
|- Mixer
|- Model Runtime
|- Resource Management
```

### 4.2 各层职责

#### Frontend Layer
负责界面和交互，不直接理解底层模型与实现细节。

- Web：浏览器中的现代前端。
- Desktop：桌面壳和桌面交互。
- CLI UX：命令行交互与输出呈现。

#### Transport / Adapter Layer
负责把不同入口转换成统一调用，不承载核心业务。

- CLI 命令解析后只调用应用服务。
- HTTP API 只做请求校验、鉴权、序列化、响应包装。
- Desktop Bridge 负责桌面端与后端之间的本地通信。

#### Application API Layer
这是这次重构最关键的一层。

它不是单纯的 HTTP API，而是“项目内部正式的应用接口层”。它负责：

- 统一输入输出数据结构。
- 参数归一化。
- 任务编排。
- 进度事件与任务状态。
- 错误语义。
- 对 `core` 能力的调用组织。

#### Core Domain Layer
放置真正的业务能力与模型能力。

- ASR、翻译、TTS、人声分离、台本转字幕、混音。
- 模型运行期加载与释放。
- 资源下载、校验、状态检查。

这一层不负责前端，也不负责 HTTP。

---

## 五、为什么要先做 API 层
如果不先建立中间 API 层，后面无论换 Web、换 GUI 还是保留 CLI，都会继续出现这些问题：

- 每个前端自己组织参数。
- 每个入口自己决定调用顺序。
- 每个入口各自处理错误和状态。
- 底层实现一改，多个入口都得跟着改。

先做 API 层的好处是：

1. 后端能力先稳定下来，再谈前端替换。
2. CLI 可以先作为最便宜的验证入口。
3. Web 和 Desktop 只接统一接口，不直接碰底层模块。
4. 后续无论 GUI 技术怎么换，后端主线不再跟着重写。

---

## 六、Application API 层的目标职责
这一层应该成为项目真正的“业务入口”。

建议第一批接口围绕项目最核心的能力定义，而不是围绕现有模块目录命名。

### 6.1 建议的服务划分

#### PipelineService
负责整条处理链路的启动、编排与结果收集。

例如：

- `run_audio_pipeline(...)`
- `run_script_pipeline(...)`
- `resume_task(...)`
- `collect_artifacts(...)`

#### SubtitleService
负责统一字幕中间结构、字幕导入导出、字幕变换。

例如：

- `load_subtitle(...)`
- `build_subtitle_from_asr(...)`
- `translate_subtitle(...)`
- `split_subtitle(...)`
- `export_subtitle(...)`

#### ModelService
负责模型注册、状态、下载、校验、移除。

例如：

- `list_models()`
- `get_model_status(id)`
- `install_model(id)`
- `verify_model(id)`
- `remove_model(id)`

#### ResourceService
负责路径、缓存、配置生成、资源检查。

例如：

- `ensure_workspace()`
- `get_runtime_paths()`
- `check_required_resources()`

#### TaskService
负责长任务状态与进度事件。

例如：

- `create_task(...)`
- `get_task(task_id)`
- `list_task_logs(task_id)`
- `cancel_task(task_id)`

### 6.2 这一层不该做什么

- 不直接渲染 UI。
- 不直接承载具体 HTTP 框架逻辑。
- 不把每个底层类都原样暴露给前端。
- 不让前端直接知道模型目录、缓存目录、内部 JSON 结构。

---

## 七、前端重构方向
你已经明确不再继续沿用 PySide6 作为长期 GUI 方案，这个方向是合理的。

### 7.1 前端目标
未来的前端应该满足：

- 组件化。
- 状态更容易管理。
- 界面和后端解耦。
- Web 和 Desktop 能共享尽可能多的 UI 与交互逻辑。

### 7.2 建议的结构方向
长期建议是：

- Web Frontend：现代组件式前端。
- Desktop Frontend：与 Web 共用 UI 层，再加桌面壳。
- CLI：保留，但只作为应用 API 的文本入口。

这里先不在文档里锁死具体框架名称，但架构方向应固定为：

**前端是可替换层，Application API 才是长期稳定层。**

### 7.3 对当前 GUI 的判断
当前 `src/gui/` 已经承载了很多可用功能，因此短期不建议一边保旧 GUI，一边继续给它堆深层逻辑。

更合理的策略是：

- 旧 GUI 进入维护模式。
- 新前端不直接复刻旧 GUI 的内部调用方式。
- 等应用 API 成形后，再开始新前端接入。

---

## 八、当前项目与目标架构的对照

### 8.1 入口层

#### CLI
当前现状：已实现。

- 已有 Click 命令入口。
- 已有主流程命令和模型管理命令。

主要差距：

- 仍有部分命令更接近“直接调用底层能力”。
- 还没有完全收束为“调用统一应用服务”的形式。

建议方向：

- CLI 保留。
- 后续逐步改成 Application API 的第一批正式消费者。

#### GUI
当前现状：已实现，但属于旧前端。

- 现有 PySide6 GUI 功能覆盖不少场景。
- 但它现在并不适合作为未来架构的中心。

主要差距：

- 与底层调用耦合较深。
- 不适合作为长期统一前端方案。

建议方向：

- 不继续把新能力优先堆到旧 GUI。
- 未来以新前端替代，而不是继续扩建旧 GUI。

### 8.2 调度层 / 流水线层
当前现状：部分实现，已有较成熟骨架。

- `src/core/pipeline/` 已具备路径规划、步骤解析、执行与产物收集。

主要差距：

- 更偏向当前音频主流程。
- 还没有成为所有入口统一依赖的应用编排层。
- 与未来任务系统、API 层的关系还没正式建立。

建议方向：

- 保留现有流水线层作为后端执行骨架。
- 在其上增加 Application API，而不是直接把它暴露给前端。

### 8.3 业务模块层
当前现状：大多已实现。

包括：

- `ASR`
- `Translate`
- `TTS`
- `VocalSeparator`
- `ScriptToSubtitle`
- `Mixer`

主要差距：

- 各模块已经能用，但统一输入输出边界还不够清晰。
- 还缺一层稳定的服务编排与 DTO。

建议方向：

- 不急着重写模块内部实现。
- 优先通过 Application API 收束调用方式。

### 8.4 模型与资源层
当前现状：正在内聚。

- 模型注册、下载、状态、校验已经开始收回项目内部。
- 这部分会成为 Application API 的重要基础能力。

主要差距：

- 还需要和任务、配置、前端提示进一步对齐。

建议方向：

- 继续保持“资源层在后端内聚”的方向。
- 但暂时不要让它抢占整个重构主线。

---

## 九、统一数据模型在新架构中的位置
统一字幕中间格式仍然重要，但它不再是“整个重构的第一动作”，而是：

**Application API 成形过程中必须同步推进的核心数据层工作。**

也就是说：

- 以前的思路是“先统一字幕中间格式，再谈别的”。
- 现在更合适的思路是“先定义 API 层边界，同时明确 API 层要消费和返回的统一数据结构”。

这会让统一数据模型不再孤立存在，而是直接服务于：

- PipelineService
- SubtitleService
- Web / CLI / Desktop 的统一输入输出

建议统一的数据对象至少包括：

- `SubtitleDocument`
- `SubtitleSegment`
- `SpeakerInfo`
- `TranslationResult`
- `SynthesisResult`
- `TaskStatus`
- `ModelStatus`

---

## 十、建议的目标目录方向
以下是方向性的目标结构，不要求一次到位：

```text
src/
|- app/
|  |- services/
|  |- dto/
|  |- tasks/
|  `- errors/
|- api/
|  |- http/
|  |- cli/
|  `- desktop/
|- core/
|  |- asr/
|  |- translate/
|  |- tts/
|  |- vocal_separator/
|  |- script_to_subtitle/
|  |- mixer/
|  |- pipeline/
|  `- resources/
|- frontend/
|  `- web_or_desktop_client/
`- utils/
```

说明：

- `app/` 是新的应用 API 层。
- `api/` 是不同入口的适配层。
- `core/` 保留为业务能力层。
- 前端最终不应继续和 `core/` 直接耦合。

---

## 十一、分阶段路线
这次路线建议按“先 API，后前端”推进。

### Phase 1：定义 Application API 边界
目标：

- 明确项目内部正式服务接口。
- 定义第一批应用服务与 DTO。
- 确定哪些能力必须经过这层才能被上层使用。

优先事项：

- 确定 `PipelineService`、`SubtitleService`、`ModelService` 的最小接口。
- 明确任务状态、错误模型、结果结构。

### Phase 2：让 CLI 先接入 API 层
目标：

- 把 CLI 作为第一批正式消费者。

优先事项：

- 将关键命令改为调用应用服务，而不是直连底层模块。
- 用 CLI 验证 API 层是否足够稳定。

### Phase 3：统一核心数据结构
目标：

- 为 API 层补齐稳定 DTO。
- 收束字幕、分段、翻译、配音、模型状态的统一表达。

优先事项：

- 先从字幕和任务结果开始。
- 保留对旧字典结构的兼容层。

### Phase 4：暴露 HTTP API
目标：

- 把 Application API 通过正式 HTTP 层对外提供。

优先事项：

- 增加请求/响应 schema。
- 增加任务查询、进度查询、模型状态查询。

### Phase 5：重做前端
目标：

- 基于统一 API 层重建 Web 和 Desktop。

优先事项：

- 先做 Web。
- 桌面端复用同一套前端与 API 调用模型。
- 旧 GUI 逐步退场。

---

## 十二、当前最重要的架构原则
后续所有实现与重构，建议都遵守下面六条原则：

1. 先统一应用接口，再统一界面。
2. 前端只调用 API 层，不直接碰 `core`。
3. HTTP 只是暴露方式，Application API 才是核心。
4. 先让 CLI 跑通新架构，再上 Web 和 Desktop。
5. 旧 GUI 进入维护模式，不再承担长期架构中心角色。
6. 重构目标是“让后端值得被多个前端共享”，而不是单纯换一套界面技术。

---

## 十三、当前结论
AsmrHelper 现在最合理的重构路线不是“先重写 GUI”，也不是“先继续在旧入口上补功能”，而是：

1. 先把后端整理成统一的 Application API 层。
2. 再让 CLI 成为第一批正式消费者。
3. 然后暴露 HTTP API。
4. 最后基于这层 API 重做 Web 和 Desktop 前端。

换句话说：

- 这次重构的中心不是前端框架。
- 这次重构的中心是中间 API 层。

只要这一层立住，Web、CLI、Desktop 才能真正开始共享同一套后端能力。

---

## 十四、延后议题与补充意见
以下意见已经记录，但当前不作为 API 层第一阶段的主线工作。它们会在后续资源层、安装层或前端替换阶段重新纳入。

### 14.1 安装与下载体系补充

- 支持对“需要下载的内容”进行统一管理，而不只限于本地模型。
- 将大型依赖与可选资源纳入统一下载视角，例如 PyTorch / CUDA 线、额外模型包、可选运行组件。
- 允许根据机器环境提供推荐安装项，例如根据 CPU / GPU 情况给出不同安装建议。
- 长期可以考虑把“自动检测 + 提供安装选项”纳入安装入口，但这不是当前 API 层第一阶段的阻塞项。

### 14.2 模型管理与下载管理边界

- `model` 管理与“下载管理”不一定完全等价，后续应进一步拆清。
- 模型本身会有较多配置项，未来需要单独设计，但不在当前 API 层第一阶段先展开。
- 当前阶段优先保持资源层可用，不急于一次性把所有模型配置系统重写。

### 14.3 模块级重构方式

- 后续重构应尽量逐模块推进，而不是一次性全仓库翻修。
- 先建立统一应用接口层，再逐步把各模块纳入这层。
- 安装层、资源层、模型层、字幕层、流水线层都应按边界逐步迁移，而不是并行大改。

### 14.4 当前处理原则

这些补充意见先作为“已确认但暂缓实施”的后续议题保留：

1. 先不让它们打断 API 层主线。
2. 先完成应用接口层的边界与最小服务集。
3. 等 CLI 接入和核心 DTO 成形后，再回头拆安装管理、下载管理与模型配置层。


一些可能更加细化的对模块的意见

- 应该逐个模块重构
- 或许按照下面的顺序 

- 先支持下载管理（管理各种需要下载的部分，本地模型，依赖， 可选择的下载项目， 检测CPU进行选择下载）
- 大型依赖例如pytouch， cuda， 应该加入

- model 管理和下载管理分开 
- model 会有很多配置项目，重构再说

- 待定
