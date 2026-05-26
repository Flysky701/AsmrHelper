# GUI 启动脚本连接稳健性修复日志

## 对应计划

- `docs/plan/2026-05-20-gui-launch-connection-hardening.md`

## 问题

- 当前桌面前端 API 固定请求 `http://localhost:8000/api/v1`。
- 原有 `GUIRun.bat` 只检查 `8000` 端口是否处于监听状态，就默认后端可用。
- 如果该端口被其他进程占用，脚本仍会继续启动桌面端，最终表现为前端无法正常连接后端。
- 原有脚本在发现已编译桌面端可执行文件存在时，也不会确认 `desktop/dist` 是否可用。

## 原因

- 端口监听只能说明“有进程在占用端口”，不能说明“ASMR Helper 后端已经就绪”。
- 启动脚本缺少 `/health` 级别的应用健康检查。
- 已编译桌面端依赖 `desktop/dist` 作为静态资源来源，但脚本没有校验这一点。

## 修改

- 重写 [GUIRun.bat](D:/WorkSpace/AsmrHelper/GUIRun.bat) 的关键启动判断逻辑：
  - 增加 `BACKEND_HEALTH_URL`
  - 增加 `DIST_INDEX`
  - 当 `8000` 端口已被占用时，先调用 `:check_backend_health`
  - 如果健康检查失败，则直接报错退出，不再盲目启动桌面端
  - 启动后端时显式使用 `--host 127.0.0.1 --port 8000`
  - 等待后端启动时改为反复检查 `/health`
  - 启动已编译桌面端前，要求 `asmr-helper.exe` 和 `desktop/dist/index.html` 同时存在
  - 若缺少 `dist`，则自动回退到 `npx tauri dev`
- 顺手去掉了脚本里重复的 `where node` 调用。

## 影响

- 脚本现在能区分：
  - 端口被 ASMR Helper 后端正常占用
  - 端口被其他程序占用
- 这能避免“桌面端正常启动，但所有接口都像断连一样失败”的假象。
- 启动已编译桌面端时，对前端静态资源是否存在也有了基本兜底。

## 验证

- 静态核对结果：
  - 前端 API 基址与脚本后端端口一致，均为 `8000`
  - 后端确实提供 `/health`
  - `desktop/dist/index.html` 当前存在
- 本轮主要是脚本层稳健性修复，未直接自动化执行 `GUIRun.bat` 全链路，以避免在当前终端中额外拉起后台窗口和长驻进程。

## 风险

- 健康检查仍依赖系统 `curl` 可用。
- 当前桌面端 API 基址仍是代码内固定的 `localhost:8000`；若未来需要切换端口或远程后端，建议再补环境变量化配置。
