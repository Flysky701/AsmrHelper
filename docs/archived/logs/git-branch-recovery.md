# Git 分支恢复日志

## 对应计划

- `docs/plan/2026-05-20-git-branch-recovery.md`

## 问题

- 当前仓库停留在 `refactor/re-design`，但该分支没有任何提交历史。
- 在该状态下，Git 将整份项目识别为首次提交内容，导致 `git status` 显示整仓新增，难以继续正常切换和判断真实改动。

## 原因

- `HEAD` 指向了一个 unborn branch，而不是已有提交历史的正常分支。
- 仓库对象本身未损坏，问题主要来自分支状态异常。

## 修改

- 为 `refactor/re-design` 创建了首个安全提交：`b64e716 chore: preserve refactor re-design snapshot before branch recovery`。
- 将当前工作分支切换回 `refactor/unified-subtitle-format`。
- 额外创建了一个 stash：
  - `stash@{0}: temp: preserve re-design worktree after branch recovery`
  - 用于保留切换后残留在工作区中的未跟踪文件副本。

## 影响

- `refactor/re-design` 不再是无提交分支，当前快照已经进入可回溯历史。
- `refactor/unified-subtitle-format` 可以作为后续继续整理与开发的基线分支使用。
- 当前仓库仍存在本地分支与远端分支分叉的问题，需要后续单独整理。

## 验证

- 已确认 `git log --oneline -1 refactor/re-design` 返回提交 `b64e716`。
- 已确认可成功切换到 `refactor/unified-subtitle-format`。
- 已确认 `git stash list --max-count=3` 中存在本次恢复产生的 stash 记录。

## 风险

- `refactor/unified-subtitle-format` 当前仍落后远端 4 个提交，拉取或重整前需要先确认是否直接 fast-forward。
- stash 中包含 `desktop/` 下的依赖与构建产物，后续恢复时应按需筛选，不建议整包盲目弹回。
