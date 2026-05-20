# 项目现状与 Git 恢复差异核查日志

## 对应计划

- `docs/plan/2026-05-20-project-status-and-git-recovery-audit.md`

## 问题

- 用户反馈 Git 恢复后状态不稳定，希望确认当前项目现状。
- 本线程前文关于 `docs/` 文档、HTTP 契约补强和测试状态的描述，与当前仓库现状疑似不一致。

## 原因

- 当前本地 `refactor/re-design` 与恢复备份分支已经分叉。
- 部分前文提到的提交与文档不在当前可达历史线上。
- `tests/test_script_subtitle_service.py` 存在单跑通过、合并套件失败的套件级污染问题。

## 核查结果

- 当前分支：`refactor/re-design`
- 当前 HEAD：`2404263`
- 当前工作区：`git status` 干净
- `git fsck --full` 未发现缺失对象，但存在多条 `dangling blob`
- `git reflog` 显示曾在 `backup/refactor-re-design-rescue-20260520` 与 `refactor/re-design` 之间来回切换
- `git log --graph --all` 显示：
  - 当前本地 `refactor/re-design` 在 `8229b7f` 之后直接提交了 `2404263`
  - 恢复相关提交 `b64e716`、`8767b2d` 留在 `backup/refactor-re-design-rescue-20260520` / `origin/refactor/re-design`
  - `2dbf1dc` 只出现在 reflog，不被当前分支包含
- 当前仓库顶层存在 `desktop/`、`src/`、`tests/`，但不存在 `docs/`
- 前文多次提到的 `docs/plan/*.md`、`docs/log/*.md`、路线图/清单文档在当前分支均不存在
- 当前代码中未保留前文提到的 HTTP 契约补强：
  - `src/api/http/schemas/tasks.py` 没有 `kind`、`terminal`、`success`
  - `src/api/http/schemas/pipeline.py` 没有 `warnings`、`step_errors`
  - `src/api/http/schemas/subtitles.py` 没有 `artifacts`、`debug_dir` 响应增强
  - `src/app/dto/script_subtitle.py` 的 `ScriptSubtitleResult` 也没有 `debug_dir`
- 当前测试状态：
  - `uv run --python 3.12 pytest -q tests/test_script_subtitle_service.py`：`13 passed`
  - `uv run --python 3.12 pytest -q tests/test_http_api.py tests/test_app_api.py tests/test_script_subtitle_service.py`：`74 passed, 5 failed`
  - 5 个失败全部位于 `tests/test_script_subtitle_service.py`
- 失败特征与前文提到的问题一致：单独跑通过，合并套件失败，属于套件级 monkeypatch / 模块重载污染
- 当前测试文件仍在 patch `src.app.services.script_subtitle_service._load_pipeline_runtime`，没有保留前文提到的更稳的修复版本

## 影响

- 当前本地 `refactor/re-design` 不是前文描述中的那条“带 docs、带契约补强、带测试修复”的工作线。
- 如果继续在当前分支上推进，需要先明确是：
  - 以当前本地分支为准继续开发
  - 还是把恢复备份分支中的文档/提交择优摘回来
- 当前测试并非稳定全绿，`script_subtitle_service` 相关测试污染仍然存在。

## 验证

- 使用了 `git status`、`git fsck --full`、`git reflog -10`、`git log --graph --oneline --decorate --all -12`
- 抽查了：
  - `src/api/http/schemas/tasks.py`
  - `src/api/http/schemas/pipeline.py`
  - `src/api/http/schemas/subtitles.py`
  - `src/app/dto/script_subtitle.py`
  - `src/app/services/script_subtitle_service.py`
  - `tests/test_script_subtitle_service.py`
- 运行了针对性测试确认当前状态

## 风险

- `2dbf1dc` 之类仅出现在 reflog 的提交，若 reflog 过期，后续追溯会更困难。
- 当前 `docs/` 目录已在本次核查中重新创建，仅用于保存分析记录；不代表恢复前那批文档已经回到当前分支。
