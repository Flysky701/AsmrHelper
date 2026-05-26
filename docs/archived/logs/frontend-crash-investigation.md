# 前端闪退排查与修复日志

## 对应计划

- `docs/plan/2026-05-20-frontend-crash-investigation.md`

## 问题

- 用户反馈桌面前端存在闪退问题。
- 前端构建本身已可通过，但桌面窗口在 `tauri dev` 启动阶段直接退出。

## 原因

- 闪退不是 React 页面运行时报错，而是 Tauri 主进程在启动时 panic。
- 实际启动日志显示 `desktop/src-tauri/tauri.conf.json` 中的插件配置写法与当前插件版本不兼容：
  - `plugins.dialog` 使用了 `{}`，但当前插件配置反序列化期望 `unit`
  - 修掉 `dialog` 后，`plugins.http` 也出现同样的 `invalid type: map, expected unit`
- 当前前端代码实际使用的是浏览器 `fetch`，并未消费 `@tauri-apps/plugin-http` 的运行时接口，因此插件配置块不是必需的。

## 修改

- 新增本计划和本日志文档。
- 更新 [desktop/src-tauri/tauri.conf.json](D:/WorkSpace/AsmrHelper/desktop/src-tauri/tauri.conf.json)：
  - 移除 `plugins.dialog` 配置块
  - 移除 `plugins.http` 配置块
- 保留 Rust 侧插件注册不变，仅清理不兼容的配置声明。

## 影响

- Tauri 桌面端不再因插件配置反序列化失败而在启动时 panic。
- 当前闪退根因已确认为配置层不兼容，而不是前端页面代码崩溃。
- `npm run build` 和 `cargo check` 仍然保持通过。

## 验证

- 初次复现：
  - `cd desktop && npm run tauri dev`
  - 观察到：
    - `PluginInitialization("dialog", "invalid type: map, expected unit")`
    - 修掉 `dialog` 后继续观察到：
    - `PluginInitialization("http", "invalid type: map, expected unit")`
- 修复后验证：
  - `cd desktop && npm run tauri dev`
  - 结果：进入 `Running target\\debug\\asmr-helper.exe`，未再出现插件初始化 panic
  - `cd desktop && npm run build`
  - 结果：通过
  - `cd desktop/src-tauri && cargo check`
  - 结果：通过

## 风险

- 本次修复解决的是启动级闪退；后续如果桌面端在具体页面交互时仍有异常，需要继续按页面或 API 调用链排查。
- 当前 `@tauri-apps/plugin-http` 虽然仍保留在依赖中，但前端实际未使用；后续可以再决定是否彻底移除依赖与 Rust 插件注册。
