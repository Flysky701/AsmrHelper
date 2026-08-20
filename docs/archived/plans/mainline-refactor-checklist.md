# AsmrHelper 主链路重构检查清单

日期：2026-05-23

目的：把前期讨论里已经比较明确的判断，收束成一份适合当前仓库结构的落地清单。它不替代已有的契约文档和领域设计，而是回答一个更直接的问题：

> 现在这轮重构，什么必须优先收束，什么暂时不要继续扩散？

## 1. 当前主链路

本阶段默认只保护并打磨这一条主链路：

```text
Workbench 选择输入
-> 创建 pipeline task
-> 后端执行
-> TaskCenter 展示阶段与状态
-> Artifact 输出
-> 预览 / 播放
```

只要某个改动不能直接提升这条链路的可理解性、可执行性或可验证性，就不应该抢到当前优先级前面。

## 2. 与现有文档结构的对应关系

讨论里原本建议把检查表放到 `docs/plans/refactor-checklist.md`，但当前仓库已经完成了 `docs/` 目录重组，因此这里落到 `docs/roadmap/`。

相关文档的对应关系如下：

- 当前主链路契约：[`../../contracts/mainline-v1.md`](../../contracts/mainline-v1.md)
- 当前数据参数契约：[`../../contracts/schemas-v1.md`](../../contracts/schemas-v1.md)
- 领域责任边界：[`../../domains/README.md`](../../domains/README.md)
- 前端结构蓝图：[`../../designs/desktop-ui-redesign-blueprint.md`](../../designs/desktop-ui-redesign-blueprint.md)
- Provider 与设置契约：[`../../contracts/provider-v1.md`](../../contracts/provider-v1.md)
- 当前实现兼容说明：[`../../contracts/compatibility.md`](../../contracts/compatibility.md)

## 3. 先冻结，再推进

### 当前默认冻结项

- 已删除的旧 GUI `src/gui/`，不得为了兼容旧文档重新引入
- 与主链路无关的页面精修
- 不直接服务主链路的复杂视觉动效
- “先把所有旧代码重写一遍”的大爆炸式迁移

### 当前默认推进项

- 先按 [`../../contracts/mainline-v1.md`](../../contracts/mainline-v1.md) 收束主链路契约
- 再按 [`../../contracts/schemas-v1.md`](../../contracts/schemas-v1.md) 固定数据参数，并按 [`../../contracts/compatibility.md`](../../contracts/compatibility.md) 处理旧字段
- `desktop/` 中围绕主链路的页面结构与信息层级
- pipeline task 的状态、阶段、时间戳、产物入口
- 与主链路直接相关的接口契约澄清
- Legacy 迁移代码的风险标记与边界梳理

## 4. Legacy 迁移代码检查

很多核心逻辑来自旧版本迁移，这类代码最危险的点不是“不能跑”，而是“概念和新结构已经不一致，但暂时还能跑”。

每次碰到这类代码时，至少检查下面几项：

| 检查项 | 处理建议 |
|---|---|
| 是否来自 old version | 补迁移标记或说明来源 |
| 是否仍沿用旧字段名 / 旧语义 | 记录到迁移清单 |
| 是否绕过 task / artifact / workspace 体系 | 视为高优先级风险 |
| 是否混合 UI 参数、业务逻辑、文件路径处理 | 尽量拆分 |
| 是否存在临时兼容逻辑却没有说明 | 必须补注释 |
| 是否直接读写输出路径而不是经过产物抽象 | 需要收束 |

推荐统一标记格式：

```python
# LEGACY_MIGRATED:
# 从旧版本迁移而来，尚未完全适配 task/session/artifact 结构。
# TODO: 收束路径依赖，转为 workspace + artifact。
```

## 5. UI 收束检查

这轮桌面端改造的重点，不是“做得更像后台系统”，而是让主链路更像生产工作台。

### Workbench 必须回答的问题

- 用户是否能在 5 秒内知道第一步做什么
- 用户是否能一眼看懂本次任务要经过哪些阶段
- 用户是否能在执行前确认本次输入、预设和输出预期
- 高级参数是否已经退到次级区域，而不是占据主舞台

### TaskCenter 必须回答的问题

- 当前任务处在哪个阶段
- 失败是卡在哪一步
- 成功后主产物入口在哪里
- 日志是否被降级到详情区，而不是继续霸占主视线

## 6. 日志检查

日志系统暂时不求“最终形态”，但必须逐步统一关键字段。至少应能关联：

```text
task_id
stage
status
input_path 或 input_ref
duration_ms
error_type
```

注意：中文文案在桌面应用内可正常显示时，不应把终端或读取工具中的乱码显示当作产品缺陷。涉及文档和源码读取时，优先确认文件编码和读取方式。

检查时优先看：

- 是否仍有大量随手 `print`
- 是否任务状态已变更但日志缺少对应阶段信息
- 是否错误信息可见但无法关联到具体输入文件
- 是否 UI 展示阶段和日志阶段完全脱节

## 7. 接口与状态检查

前后端接口暂时不一定一步到位，但至少要保证主链路能稳定消费这些信号：

- 任务创建返回值中，是否能拿到后端 task id
- 任务轮询是否能稳定回传 `state / progress / message / detail`
- 终态时是否能明确区分 `completed / failed / cancelled / skipped`
- 产物是否能通过统一结构返回，而不是靠前端猜路径

如果某个任务页面开始依赖“额外补字段才能用”，应优先回查 [`../../contracts/mainline-v1.md`](../../contracts/mainline-v1.md) 和 [`../../contracts/schemas-v1.md`](../../contracts/schemas-v1.md)。

## 8. 本阶段实施顺序

建议按下面的顺序推进，风险最低：

1. 先完成主链路 V1 契约收束。
2. 固定主链路 V1 数据参数契约。
3. 再修正主链路页面的状态连贯性。
4. 收束 Workbench 和 TaskCenter 的信息结构。
5. 补主链路相关的状态字段、时间戳、产物入口。
6. 再回头清理 Legacy 迁移边界和更深层的服务拆分。

## 9. 完成标准

可以认为这轮“讨论结果落地”基本完成，当且仅当：

- Workbench 已经围绕输入 -> 流水线 -> 执行组织
- TaskCenter 已经围绕阶段 -> 产物 -> 排障组织
- 主链路状态字段足够支持前端判断阶段和终态
- 本文档中的冻结边界没有被继续打破
- 后续工作已经可以直接从本清单继续拆任务，而不需要重新解释方向
