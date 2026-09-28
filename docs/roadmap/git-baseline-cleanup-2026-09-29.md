# Git 基线整理记录（2026-09-29）

本文前半部分为操作前审计，执行情况见末尾「授权后的执行记录」。初次网络失败已在提升执行权限后解决。

## 已确认的状态

本次仅检查本地 Git 历史并编写清单。远程访问因本机代理连接失败而未完成，下面的 `origin/*` 是本地缓存，不能视为 GitHub 最新状态。GitHub Releases、开放 PR 和分支保护尚未核实。

- 当前工作分支：`codex/whisper-tts-exploration`，提交 `33e3ab1`。
- 当前分支比缓存中的同名远程分支多 9 个提交，比本地 `master` 多 27 个提交。
- 本地 `master` 为 `902b501`；缓存中的 `origin/master` 为 `9ce0e5f`，两者分叉。
- `origin/master` 有当前分支不可达的两个提交：`056d13f`（旧资源清理及 API 入口统一）和 `9ce0e5f`（合并提交）。该侧相对共同祖先涉及 115 个文件，必须检查其意图是否仍适用于当前源码。
- 工作区有既有未跟踪目录 `audit/`；有一条历史恢复 stash。二者均需保留。
- 当前仅有一个 Git worktree。

## 分支分类

以下判断依据提交可达性，不代表功能已经测试或正式发布。

### 历史已包含在当前分支中

当前基线备份和归属确认后，可清理以下本地临时分支引用：

- `codex/experience-alignment-recovery`
- `codex/full-module-repair`
- `feature/new_gui`
- `feature/pdf-to-vtt`
- `refactor/re-design`
- `refactor/unified-subtitle-format`

本地 `master` 也已包含在当前分支中，但应作为长期主分支保留，待统一基线后更新。不要依据本地分支的可达性直接删除同名远程分支；它们有些指向不同历史。

### 需要进一步检查和保存

| 本地分支 | 当前分支不可达的提交数 | 补丁等价检查 |
| --- | ---: | --- |
| `feature/clone-instruct-prompt` | 1 | 1 个提交未找到等价补丁 |
| `fix/todo-regression-tests-gui` | 11 | 10 个提交存在等价补丁，1 个未找到 |
| `backup/refactor-re-design-rescue-20260520` | 2 | 1 个提交存在等价补丁，1 个未找到 |

未找到等价补丁不等于功能缺失，可能已被后续重构覆盖；需检查差异后再决定归档或集成。

## 发布标签

本地存在以下标签，日期为目标提交日期：

| 标签 | 提交 | 日期 |
| --- | --- | --- |
| `V1.0.0` | `7280847` | 2026-04-11 |
| `V0.5.0` | `8f3bea6` | 2026-04-12 |
| `V0.5.1` | `dee9d5f` | 2026-04-12 |
| `V0.6.0` | `7ab49cd` | 2026-05-12 |

版本号与提交日期顺序不一致。标签与 GitHub Release 不是同一个对象，现阶段无法确认是否都有关联发布。建议保留旧标签及发布资产，用发布说明解释旧版本序列；下一版本号在核实已发布版本后决定。

## 建议目标

- `master`：通过验证的稳定基线。
- `dev`：若当前源码还在验收中，将其整理为持续开发基线。
- `feature/*`、`fix/*` 或现有 `codex/*`：按任务短期存在，合并后清理。
- 正式发布以不可移动的版本标签标识。

## 执行顺序

1. 保存 refs 清单和 Git bundle，验证 bundle 可读取；另存未跟踪的 `audit/`，明确保存恢复 stash。bundle 不包含未跟踪文件和忽略文件。
2. 恢复远程访问，抓取最新 refs，核实 Releases、开放 PR、默认分支和保护规则。
3. 以当前 `33e3ab1` 为候选开发基线，审查远程主分支独有变更和三个未完全包含的本地分支。整合必要改动并执行相应回归。
4. 依验收状态决定将结果放入 `dev`，还是合并到稳定 `master`。通过正常合并保留历史。
5. 清理已包含且没有在用任务的临时分支；远程分支逐个核实后处理。
6. 补充下一次发布说明和分支约定，保留历史版本的可追溯性。

本清单不将最新提交视为已通过产品验收。基线归属、远程发布记录和未合并改动确认前，不执行分支删除、标签移动、历史重写或强制推送。

## 授权后的执行记录

用户明确授权分支合并修改，采用 `master` 稳定主线与 `dev` 开发基线。

### 备份

- 备份目录：项目内 `.tmp/git-cleanup-20260929/`，不纳入提交。
- `repository.bundle` 保存整理前所有 Git refs 可达历史，包括本地/远程分支、标签和 stash；`git bundle verify` 通过。
- bundle SHA-256：`971F9C25A06CBE9CDF4842D08DCF9533EB744313EEDCF3B3B1FE9969CD13B11A`。
- `refs-before.txt`、`status-before.txt` 保存操作前引用与状态；`audit/` 和本清单原稿另存副本。原工作区的 `audit/` 和恢复 stash 保留。
- 本地旧分支归档到 `refs/archive/branch-cleanup-20260929/local/<原分支名>`；远程引用另存到对应 `remote/<原分支名>`，不会出现在日常分支列表中。

需要恢复旧本地分支时，例如：

```powershell
git branch recovered-whisper refs/archive/branch-cleanup-20260929/local/codex/whisper-tts-exploration
```

完整 bundle 不依赖当前仓库对象，可在另一个仓库中用 `git fetch <bundle路径> <原ref>:<恢复ref>` 恢复；不要直接覆盖正在使用的分支。

### 远程核实

- 通过配置代理重新访问并抓取远程分支，远程主分支仍为 `9ce0e5f`。GitHub 查询无开放 PR，现有分支的 `protected` 均为 false。
- GitHub 有 3 个 Release：`V0.5.0`、`V0.5.1`、`V0.6.0`，均无额外上传资产；`V1.0.0` 仅有标签，无对应 Release。
- 四个本地标签与远程同名标签的提交 ID 不同，但逐一比较 tree，文件内容全部相同。远程标签分别为 `b1b7dcc`、`8c42a4e`、`c8523c8`、`9fa7c52`；独立抓取到 `refs/archive/remote-tags-20260929/*`，没有覆盖本地标签或移动远程标签。

### 合并取舍

- 从 `33e3ab1` 建立 `dev`，正常合并 `origin/master`，保留双亲历史。
- 接受主线的工具/字幕接口统一、配置直接导入、无调用接口和方法清理、直接依赖声明及锁文件更新。
- 保留现行工作台和声音库流程、克隆 manifest 与路径处理；维持独立批处理页面已删除的状态。
- 保留 2026-09-24 后明确归档的设计及验收资料，不重复执行远程较早的历史文档删除。同步当前基线文档和分支使用约定。
- 补齐后来新增代码中的 `src.config` 导入，以及恢复流程和翻译异常测试对现行接口的调用；行为断言保持有效。
- 两个未完全包含的本地功能分支，与各自远程版本的最终 tree 相同，但不属于当前提交祖先。因此按历史分支归档，未将其称为已合并，也未把旧 GUI/检查点实现重新引入当前架构。
- 旧恢复分支为历史全仓快照，归档保留；当前代码已使用后续桌面与任务架构。

### 分支清理范围

- 本地日常分支收敛为 `master` 与 `dev`。旧本地 `master` 的 `902b501` 已包含在 `dev`，保存归档引用后将本地 `master` 对齐远程稳定主线。
- 远程只清理已完整包含在 `dev` 的 4 个临时分支：`cleanup/remove-obsolete-assets`、`codex/full-module-repair`、`codex/whisper-tts-exploration`、`refactor/re-design`。
- 远程仍保留 6 个历史分支：`backup/master-before-baseline-merge-20260822`、`feature/clone-instruct-prompt`、`feature/new_gui`、`feature/pdf-to-vtt`、`fix/todo-regression-tests-gui`、`refactor/unified-subtitle-format`。其中多个是内容相同而历史不同的旧分叉，最后一个还有旧 queue-workbench 脚手架提交。它们不再作为当前开发基线，本次不删除未完整合入的远程历史。
- 不改写提交历史，不推送稳定主线，不创建新版本或修改现有 Releases。

### 验证

- 首轮 Python 回归：807 passed、2 failed。两处为新测试对已删除旧接口的调用，已更新为现行接口并保留异常和恢复行为验证。
- 前端 `npm run build`（TypeScript + Vite）通过。
- 最终 Python 全量回归：`809 passed in 61.40s`。Ruff `F821/F601/F401`、`uv lock --check --offline` 和 `git diff --check` 均通过。
- 自动检查不代表真实模型推理、付费外部接口或正式桌面窗口的产品验收；`dev` 等待这些验收后再提升为稳定版。
