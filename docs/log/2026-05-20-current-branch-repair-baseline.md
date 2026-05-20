# 当前分支修复基线日志

## 对应计划

- `docs/plan/2026-05-20-current-branch-repair-baseline.md`

## 问题

- 用户已确认当前前端来自 backup，因此当前分支需要以现状为准重新整理和修复。
- 本线程前文提到的部分 docs、后端契约补强和测试修复，并未实际留在当前 `refactor/re-design` 分支。

## 原因

- 当前本地分支和恢复备份分支已经分叉。
- 前端骨架属于当前分支应保留内容，不应继续作为异常漂移处理。
- 真正缺失的是当前分支上的后端收口工作与文档沉淀。

## 当前分支现状

- 当前分支：`refactor/re-design`
- 当前 HEAD：`2404263`
- 当前主线特征：
  - 已包含 `desktop/` 桌面端前端骨架
  - 已包含 Phase 5a-5d 对应的 `AudioToolService`、`VoiceService` 与 HTTP 路由基础
  - 未保留前文提到的 `docs/plan/*`、`docs/log/*`、迁移路线图、首批清单等文档
  - 未保留前文提到的部分 HTTP 契约补强

## 与 backup 前提对齐后的判断

- `desktop/` 前端目录：
  - 视为当前分支已接受的组成部分
  - 不再作为恢复异常处理
- 当前分支真正需要重新修复的内容：
  - 后端文档沉淀
  - HTTP / DTO / task / artifact 契约补强
  - `script_subtitle_service` 相关测试稳定性

## 当前可验证状态

- `git diff --stat backup/refactor-re-design-rescue-20260520..HEAD` 显示：
  - 当前分支相对 backup 缺少一批 docs 与部分后端收口内容
  - 同时包含前端骨架与当前分支自己的新增内容
- 当前代码抽查结果：
  - `src/api/http/schemas/tasks.py` 仍是基础状态
  - `src/api/http/schemas/pipeline.py` 未补 `warnings` / `step_errors`
  - `src/api/http/schemas/subtitles.py` 未补 `artifacts` / `debug_dir` 返回增强
  - `src/app/dto/script_subtitle.py` 的 `ScriptSubtitleResult` 未扩展 `debug_dir`
- 当前测试结果：
  - `uv run --python 3.12 pytest -q tests/test_script_subtitle_service.py`：`13 passed`
  - `uv run --python 3.12 pytest -q tests/test_http_api.py tests/test_app_api.py tests/test_script_subtitle_service.py`：`74 passed, 5 failed`
  - 5 个失败全部集中在 `tests/test_script_subtitle_service.py`
  - 失败表现仍然是套件级污染特征：单独跑通过，合并运行失败

## 影响

- 当前分支可以作为新的正式修复线继续推进。
- 后续讨论和开发应以“当前分支现状”为准，而不是沿用前文未落地的假设状态。
- backup 分支更适合作为参考来源，而不是当前分支状态的替代描述。

## 后续优先级

1. 修复 `tests/test_script_subtitle_service.py` 的套件级污染，先恢复测试稳定性。
2. 重新补齐当前分支需要保留的 docs 和修复记录。
3. 在当前分支重新推进 HTTP / DTO / task / artifact 契约收口。

## 风险

- 如果后续直接从 backup 摘回内容，可能把不适合当前分支的新旧状态混在一起。
- 当前测试未稳定全绿，继续叠加功能改动会放大排障难度。
