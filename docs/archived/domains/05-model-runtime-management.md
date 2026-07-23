# [已归档] 功能 5：模型与运行资源管理 V1 计划

## 目标

- 将“模型管理”和“运行资源检查”从页面级展示能力提升为系统级运行前提管理层。
- 统一管理模型注册表、模型状态、模型安装与卸载、运行目录和执行前置条件。
- 为功能 2、功能 3、功能 4 提供稳定的可运行性判断依据，而不是让各模块自行猜测模型和环境状态。

## 背景

- 当前仓库已经具备一组模型相关后端能力，包括模型列表、状态检查、安装、校验、删除、卸载等。
- 当前 `ModelService` 主要围绕 `models.yaml` 和 core resources service 工作，但更像“模型接口集合”，尚未被定义为完整功能域。
- 当前 `ResourceService` 仅覆盖工作目录、输出目录、模型目录的基础准备，职责偏窄。
- 当前系统还缺少统一的“任务是否具备运行前提”的判断入口，这会让功能 2、3、4 在运行前持续重复做局部判断。

## 功能定位

该功能域是整个系统的“运行前提管理层”。

它负责：

1. 管理模型注册表。
2. 管理模型状态、安装、校验、移除与卸载。
3. 管理运行目录与关键运行资源。
4. 对任务或执行器提供“当前是否可运行”的判断能力。

`ModelCatalogEntry`、`ModelRef`、模型资源字段与 `RuntimeBinding` 的横向边界以 [基础设施契约 V1](../contracts/infrastructure-contracts-v1.md) 为准。

它不直接执行流水线或工具业务。

## 边界

### 本功能负责

- 模型资产注册与索引。
- 模型状态统一语义。
- 模型安装、校验、移除、卸载。
- 工作目录、输出目录、临时目录、模型目录的解析与准备。
- 运行时依赖和任务前置能力检查。

### 本功能不负责

- 不负责文件选择、输入识别，这些属于功能 1。
- 不负责任务入队、调度、取消、重试，这些属于功能 3。
- 不负责完整流水线业务执行，这些属于功能 2。
- 不负责单步工具业务执行，这些属于功能 4。
- 不负责前端资源页面的展示布局本身。

## V1 需要实现的功能

### 1. 模型注册表

系统需要保留并正式定义模型注册表机制。

V1 继续沿用 `models.yaml` 作为注册表来源，但其角色应明确为“系统模型清单”，而不是页面配置。

每个模型条目至少需要包含：

- `model_id`
- `kind`
- `category`
- `display_name`
- `description`
- `provider` 或 `engine`
- `install_root`
- `install_path`
- `required_files`
- `required_dirs`
- `supports_install`
- `supports_remove`
- `install_strategy`
- `api_key_config`

V1 支持的模型分类至少包括：

- `asr`
- `tts`
- `separator`
- `llm`

V1 支持的模型种类至少包括：

- `local`
- `cloud`

### 2. 模型状态统一

系统需要建立统一模型状态语义，供前端、任务系统和执行器共享。

V1 建议状态至少包含：

- `missing`
- `installing`
- `ready`
- `invalid`
- `configured`
- `unloaded`
- `error`

含义约定：

- 本地模型更常见于 `missing/ready/invalid/unloaded`
- 云模型更常见于 `configured/error`

V1 要求：

- 批量状态和单模型状态使用同一语义集合。
- 校验结果不能只返回布尔值，应返回状态与 detail。

### 3. 模型操作

V1 需要明确支持以下模型操作：

1. 列表查询
2. 单模型状态查询
3. 批量状态查询
4. 安装
5. 校验
6. 移除
7. 卸载单个运行时实例
8. 卸载全部运行时实例

V1 要求：

- 本地模型与云模型的操作边界要清晰。
- 云模型如果不支持安装或删除，应返回明确错误语义，而不是静默忽略。

### 4. 运行目录管理

系统需要统一管理以下运行目录：

- `workspace_root`
- `default_output_root`
- `default_temp_root`
- `default_models_root`

V1 要求：

- 支持默认目录解析。
- 支持显式覆盖。
- 支持目录存在性与可写性检查。
- 不再仅将其视为某个页面的展示信息。

### 5. 运行资源检查

V1 需要在模型之外，建立更完整的运行资源检查能力。

至少应检查：

- 工作目录存在性
- 输出目录存在性与可写性
- 临时目录存在性与可写性
- 模型目录存在性
- 模型可用性
- 关键依赖是否存在

V1 不要求一次性穷举所有系统依赖，但需要形成统一能力入口。

### 6. 任务可运行性判断

这是功能 5 与功能 2/3/4 最关键的衔接点。

系统需要支持回答：

- 一个 `pipeline` 任务现在是否可运行
- 一个 `tool.*` 任务现在是否可运行
- 缺失的是模型、路径、配置还是运行环境

V1 判断结果至少应包含：

- `runnable`
- `missing_models`
- `missing_resources`
- `configuration_errors`
- `warnings`

### 7. 运行时绑定输出

功能 5 还需要和功能 6 协作，为执行器生成 `RuntimeBinding`。

`RuntimeBinding` 的职责是提供执行瞬间所需的环境与资源，例如：

- 本地模型实际路径
- device
- provider runtime client
- 已通过功能 6 解析完成的 provider 接入信息

V1 要求：

- `RuntimeBinding` 只在执行时生成
- `RuntimeBinding` 不进入任务持久层
- `RuntimeBinding` 不在日志和普通查询接口中明文暴露敏感信息

## 对外 API 设计

### 模型组

- `GET /api/v1/models`
- `GET /api/v1/models/statuses`
- `GET /api/v1/models/{model_id}/status`
- `POST /api/v1/models/{model_id}/install`
- `POST /api/v1/models/{model_id}/verify`
- `DELETE /api/v1/models/{model_id}`
- `POST /api/v1/models/{model_id}/unload`
- `POST /api/v1/models/unload-all`

### 运行资源组

V1 建议保留并升级：

- `GET /api/v1/resources/status`

长期建议明确区分为：

- `GET /api/v1/runtime/resources`
- `GET /api/v1/runtime/capabilities`
- `POST /api/v1/runtime/check-task-readiness`

其中：

- `runtime/resources` 用于目录和运行资源状态
- `runtime/capabilities` 用于当前环境支持哪些能力
- `check-task-readiness` 用于任务执行前检查

## 中间层设计

### `ModelRegistryService`

职责：

- 管理模型注册表
- 查询模型定义
- 列表过滤
- 输出模型摘要

### `ModelLifecycleService`

职责：

- 安装模型
- 校验模型
- 移除模型
- 卸载运行时模型实例

### `RuntimeResourceService`

职责：

- 解析并准备运行目录
- 检查目录存在性和可写性
- 汇总资源状态

### `TaskReadinessService`

职责：

- 根据 `task_type` 和运行参数推导所需模型与资源
- 根据 `ExecutionProfile` 推导所需模型与资源
- 判断当前是否满足执行前提
- 输出结构化 readiness 结果

## 与当前实现的关系

### 可以保留的思路

- `src/core/resources/model_catalog.py` 中基于注册表的模型定义方式可以保留。
- `src/core/resources/model_service.py` 中模型列表、状态、安装、校验、删除的核心能力可以保留。
- `src/app/services/model_service.py` 作为应用层 facade 的方向可以保留。
- `src/app/services/resource_service.py` 中目录准备思路可以保留，但需要扩展。

### 必须重写或重组的部分

- `ResourceService` 当前职责过窄，需要升级为真正的运行资源服务。
- 模型状态语义需要从“接口层拼装结果”上升为统一功能域定义。
- 当前还没有任务可运行性检查能力，需要新增。
- 当前资源接口更偏展示用途，缺少运行前提管理视角。

### 明确不继承的历史包袱

- 不继承“资源页展示什么，后端就只提供什么”的方式。
- 不继承“模型是否可用由各执行器自己判断”的方式。
- 不继承“目录准备只服务于 pipeline”的方式。

## 具体实现范围

### V1 内必须落地

1. 正式确立模型注册表角色。
2. 统一模型状态语义。
3. 保留并整理模型安装、校验、删除、卸载接口。
4. 扩展运行资源检查能力。
5. 增加任务可运行性判断入口。

### V1 内暂不落地

1. 不在这一轮设计复杂的模型下载进度流。
2. 不在这一轮做跨机器模型同步。
3. 不在这一轮做自动修复全部缺失依赖。
4. 不在这一轮做前端资源页面重构。

## 风险与注意事项

- 如果功能 5 不先统一，功能 2、3、4 会继续各自复制模型与资源判断逻辑。
- 如果模型状态语义不统一，前端展示、任务可运行性判断和执行器错误会长期不一致。
- 如果只保留“资源状态展示”而不建立 readiness 判断，任务系统将很难做可靠入队和调度。

## 验收标准

- 模型注册表、模型状态、模型操作有统一功能定义。
- 运行目录与资源状态有统一检查入口。
- 系统能够判断一个任务当前是否具备运行前提。
- 功能 2、3、4 不再各自实现一套模型/资源就绪判断。

## 与现有文档的关系

- 本文档是“功能 5：模型与运行资源管理”的上游计划文档。
- 它为前四个功能域提供共同的运行前提基础。
