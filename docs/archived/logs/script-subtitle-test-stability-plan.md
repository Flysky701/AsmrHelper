# script subtitle 测试稳定性与前端构建修复计划

## 目标

- 修复 `script_subtitle_service` 相关测试在合并套件下的不稳定问题。
- 确认并修复当前前端构建问题。
- 将当前分支上的实际修复结果记录下来。

## 背景

- 当前 `tests/test_script_subtitle_service.py` 单独运行通过，但与 `tests/test_http_api.py`、`tests/test_app_api.py` 合并运行时失败。
- 初步核查显示，`test_app_api.py` 会清理并重载 `src.app` 相关模块，导致 `test_script_subtitle_service.py` 中基于字符串路径的 monkeypatch 目标漂移。
- 当前前端 `desktop/` 在未安装本地依赖时，`npm run build` 会因为缺少 `tsc` 而失败，需要先确认是否存在额外代码层构建问题。

## 步骤

1. 将 `tests/test_script_subtitle_service.py` 的打桩方式改为直接作用于当前导入的 `ScriptSubtitleService` 类。
2. 重新运行相关后端测试，确认单测与合并套件都稳定通过。
3. 在 `desktop/` 执行依赖安装、`npm run build` 与 `cargo check`，确认前端构建面状态。
4. 补充任务日志，记录修复结论和验证结果。

## 验证

- `uv run --python 3.12 pytest -q tests/test_script_subtitle_service.py` 通过。
- `uv run --python 3.12 pytest -q tests/test_http_api.py tests/test_app_api.py tests/test_script_subtitle_service.py` 通过。
- `desktop` 目录下 `npm run build` 通过。
- `desktop/src-tauri` 目录下 `cargo check` 通过。

## 风险

- 当前修复聚焦测试稳定性，不涉及 `script_subtitle_service` 业务逻辑重写。
- 前端构建问题当前判断为依赖未安装导致；若后续 Node/Tauri 版本变化，仍可能出现新的环境类问题。
