# script subtitle 测试稳定性与前端构建修复日志

## 对应计划

- `docs/plan/2026-05-20-script-subtitle-test-stability-and-frontend-build-fix.md`

## 问题

- `tests/test_script_subtitle_service.py` 单独运行通过，但与 `tests/test_http_api.py`、`tests/test_app_api.py` 合并运行时失败。
- `desktop/` 前端构建最初失败，`npm run build` 报 `tsc` 未找到。

## 原因

- `tests/test_script_subtitle_service.py` 通过字符串路径 patch `src.app.services.script_subtitle_service._load_pipeline_runtime`。
- `tests/test_app_api.py` 中存在对 `src.app` 相关模块的清理和重载，导致合并套件运行时字符串路径 patch 命中了新模块对象，而测试里提前导入的 `ScriptSubtitleService` 仍引用旧模块作用域。
- 前端构建失败的直接原因不是 TypeScript 或 Vite 代码报错，而是 `desktop` 目录本地依赖未安装，缺少 `node_modules/.bin/tsc`。

## 修改

- 更新 `tests/test_script_subtitle_service.py`：
  - 将 `_patch_pipeline()` 从 patch `_load_pipeline_runtime`
  - 改为直接 patch 当前导入的 `ScriptSubtitleService._build_pipeline`
- 新增本计划和本日志文档，记录当前分支上的修复过程与验证结果。

## 影响

- `script_subtitle_service` 测试不再依赖模块名重新导入后的运行时对象，合并套件下的打桩目标稳定。
- 前端构建链路已确认：
  - 安装依赖后 `npm run build` 可以通过
  - Tauri Rust 侧 `cargo check` 可以通过
- 当前前端没有暴露出额外的 TypeScript / Vite / Cargo 代码层构建错误。

## 验证

- 后端测试：
  - `uv run --python 3.12 pytest -q tests/test_script_subtitle_service.py`
  - 结果：`13 passed`
  - `uv run --python 3.12 pytest -q tests/test_http_api.py tests/test_app_api.py tests/test_script_subtitle_service.py`
  - 结果：`79 passed`
- 前端构建：
  - `cd desktop && npm ci`
  - `cd desktop && npm run build`
  - 结果：Vite 生产构建通过
- Tauri Rust 侧：
  - `cd desktop/src-tauri && cargo check`
  - 结果：通过

## 风险

- 本次前端构建修复主要是环境层依赖安装，不代表后续所有开发机都可跳过 `npm ci`。
- 当前未继续推进 HTTP / DTO / task / artifact 契约补强；这部分仍是当前分支后续收口重点。
