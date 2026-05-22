# AsmrHelper Aggressive Legacy Cleanup With Verifiable Acceptance Gates

## Summary

有，而且这轮清理需要把“完成”定义成一组可机器验证的边界条件，而不是“代码看起来差不多删完了”。
正式边界固定为：`HTTP API` 是唯一正式产品接口；`desktop/` 和 `src/cli.py` 仅作为实验入口保留；旧 GUI、对外 deprecated API、deprecated core re-export、legacy pipeline 执行桥全部移除。

## Key Changes

- 删除面

  - 删除 `src/gui/`、`PySide6` 依赖、旧 GUI 启动入口与仅服务旧 GUI 的工具代码。
  - 删除 `/api/v1/translation/translate` 与 artifacts legacy alias 路由。
  - 删除 `TranslationService`、`get_translation_service`、`PipelineService(use_legacy=...)`、`LegacyPipelineOrchestrator`、`src/core/pipeline/`、`PipelineConfig`。
  - 删除 `src.core.script_to_subtitle`、`src.core.subtitle_generator`、`src.core.script_processor`、`src.core.translate.subtitle_cleaner` 这类 deprecated re-export/compat 模块。
- 保留面

  - 保留正式 API：`/api/v1/llm/translate`、`/api/v1/pipeline/*`、`/api/v1/tasks/*`、`/api/v1/artifacts/by-task/*`、`/api/v1/artifacts/{artifact_id}*`。
  - 保留 `desktop/` 与 `src/cli.py`，但它们只能调用正式 API 或 canonical app/core 服务。
  - `ModelManager` 默认不作为本轮强制删除项；只有在实施时确认已无必要引用才顺带清理。

## Acceptance Gates

- Gate 1: 文件系统边界

  - `src/gui/` 不存在。
  - `src/core/pipeline/` 不存在。
  - 以下模块不存在：`src/core/script_to_subtitle/__init__.py`、`src/core/subtitle_generator.py`、`src/core/script_processor.py`、`src/core/translate/subtitle_cleaner.py`。
  - `pyproject.toml` 不再声明 `PySide6`。
- Gate 2: 仓内引用边界

  - 全仓 `rg` 不得命中以下模式：
    - `src\.gui`
    - `PySide6`
    - `/translation/translate`
    - `TranslationService`
    - `get_translation_service`
    - `use_legacy`
    - `run_legacy`
    - `LegacyPipelineOrchestrator`
    - `PipelineConfig`
    - `from src\.core\.pipeline`
    - `from src\.core import Pipeline`
  - 允许残留的 `legacy` 字样仅限非兼容语义文案或结果兼容说明，不能再指向可执行兼容入口。
- Gate 3: 导入边界

  - 在未安装 `PySide6` 的环境下，以下导入成功：
    - `import src`
    - `import src.app`
    - `import src.app.services`
    - `import src.core`
    - `import src.api.http`
  - `importlib.import_module("src.gui")` 失败。
  - `importlib.import_module("src.core.pipeline")` 失败。
  - `importlib.import_module("src.api.http.routes.translation")` 失败。
- Gate 4: API 契约边界

  - `POST /api/v1/llm/translate` 正常工作。
  - 以下接口不存在或返回未注册结果：
    - `POST /api/v1/translation/translate`
    - `GET /api/v1/artifacts/{task_id}`
    - `GET /api/v1/artifacts/{task_id}/result`
    - `GET /api/v1/artifacts/detail/{artifact_id}`
    - `GET /api/v1/artifacts/detail/{artifact_id}/file`
  - `POST /api/v1/pipeline/run`、`POST /api/v1/pipeline/batch`、`GET /api/v1/pipeline/presets` 仍保持可用。
- Gate 5: 执行路径边界

  - `PipelineService` 内部只有一条执行主路：`build_execution_plan(...) -> PipelineExecutor.execute(...)`。
  - `PipelineService` 构造函数不再接受 `use_legacy`。
  - `pipeline presets` 不再通过旧 runtime 或 `Pipeline`/`PipelineConfig` 加载。
- Gate 6: 实验入口边界

  - `desktop` 翻译调用改为 `/api/v1/llm/translate`。
  - CLI `translate` 改为基于 `LlmCapabilityService` 或等价正式能力，而不是 `TranslationService`。
  - `desktop` 与 CLI 任一入口都不得再直接或间接导入 `src.gui`、`src.core.pipeline`、deprecated re-export 模块。
- Gate 7: 文档边界

  - README 不再声称 PySide6 GUI 是正式入口。
  - README 明确说明：正式入口是 HTTP API；`desktop` 与 CLI 为实验入口。
  - README 中不再出现 `run.bat` 启动 GUI、`src/gui` 架构说明、PySide6 功能介绍。

## Test Plan

- 自动化测试

  - 更新现有 HTTP API 测试，覆盖 `/llm/translate`，删除旧翻译路由断言。
  - 更新服务测试，删除 `use_legacy` 相关断言，新增 `PipelineService` 单路径执行断言。
  - 新增静态扫描测试，专门检查 Gate 2 的禁用模式。
  - 新增导入测试，专门检查 Gate 3 的成功/失败导入矩阵。
- 验证命令

  - `uv run pytest`
  - `uv run pytest tests/test_http_api.py`
  - `uv run pytest tests/test_app_services.py`
  - `uv run pytest tests/test_facade_slimming.py`
  - `uv run python -c "import src, src.app, src.core, src.api.http"`
  - `rg -n "src\\.gui|PySide6|/translation/translate|TranslationService|get_translation_service|use_legacy|run_legacy|LegacyPipelineOrchestrator|PipelineConfig|from src\\.core\\.pipeline|from src\\.core import Pipeline" src desktop tests README.md pyproject.toml`
- 完成定义

  - 只有当 7 个 Gate 全部通过，且上述验证命令全部通过，本轮才算完成。
  - 任一 Gate 未通过，都视为“尚未完成”，不能以“仅剩文档/仅剩测试未改”结案。

## Assumptions And Defaults

- 默认接受激进切换，不保留对外兼容窗口。
- 默认允许 desktop 与 CLI 在验收时仍是不完整产品，但必须已经脱离旧兼容层。
- 默认不把“全功能业务回归”作为本轮完成条件；本轮完成条件是“架构边界清晰且可验证”。
- 默认 `ModelManager` 不是强制验收项；若保留，不能再被正式 API、desktop、CLI 当作默认新入口依赖。
