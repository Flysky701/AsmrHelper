# 前端 localhost 连接问题修复日志

## 对应计划

- `docs/plan/2026-05-20-frontend-localhost-connection-fix.md`

## 问题

- 当前用户反馈前端无法连接到 `localhost`，但具体问题点不明显。
- 前端 API 基址、脚本后端地址和后端实际绑定地址并不完全一致。

## 原因

- 前端 [desktop/src/api/client.ts](D:/WorkSpace/AsmrHelper/desktop/src/api/client.ts) 原先写死 `http://localhost:8000/api/v1`。
- 后端入口 [src/api/http/__main__.py](D:/WorkSpace/AsmrHelper/src/api/http/__main__.py) 默认绑定 `127.0.0.1:8000`。
- 启动脚本 [GUIRun.bat](D:/WorkSpace/AsmrHelper/GUIRun.bat) 的健康检查和后端启动也已经统一使用 `127.0.0.1:8000`。
- 即使当前机器上 `localhost` 也能访问，这条链路仍然不一致，后续在不同机器、不同解析策略或不同运行模式下，都容易表现成“前端无法连接 localhost”。
- 此外，前端在网络请求失败时原本会直接抛浏览器原生错误，定位成本较高。

## 修改

- 更新 [desktop/src/api/client.ts](D:/WorkSpace/AsmrHelper/desktop/src/api/client.ts)：
  - 默认 API 基址改为 `http://127.0.0.1:8000/api/v1`
  - 支持 `VITE_API_BASE` 环境变量覆盖
  - 为 `fetch` 增加网络异常捕获
  - 请求层在连接失败时统一抛出 `NETWORK_ERROR`
  - 错误消息直接带出目标后端地址
- 更新 [GUIRun.bat](D:/WorkSpace/AsmrHelper/GUIRun.bat)：
  - 在 dev 模式启动 `tauri dev` 前注入
    - `VITE_API_BASE=http://127.0.0.1:%BACKEND_PORT%/api/v1`

## 影响

- 前端、脚本、后端三者现在默认统一走 `127.0.0.1:8000`。
- 后续如果再出现连接失败，前端会直接提示具体目标地址，而不是只留下模糊的浏览器网络错误。
- 如果以后需要切到别的端口或远程后端，可以先通过 `VITE_API_BASE` 做覆盖，不必立即改代码。

## 验证

- 静态核查：
  - [src/api/http/__main__.py](D:/WorkSpace/AsmrHelper/src/api/http/__main__.py) 默认绑定 `127.0.0.1`
  - [GUIRun.bat](D:/WorkSpace/AsmrHelper/GUIRun.bat) 健康检查和后端启动已对齐 `127.0.0.1`
  - 当前前端 API 代码已改为默认使用 `127.0.0.1`
- 动态核查：
  - 临时启动后端后，当前机器上的 `curl http://127.0.0.1:8000/health` 和 `curl http://localhost:8000/health` 都可返回正常结果
  - 这说明本机并非“localhost 完全不可用”，但也进一步证明之前的问题更接近地址链路不一致，而不是单点后端失效
- 前端构建：
  - `cd desktop && npm run build`
  - 结果：通过

## 风险

- 本轮修复解决的是地址一致性和错误可观测性，不代表所有后端接口语义已经与前端完全对齐。
- 如果后续用户直接双击已编译桌面端而不通过脚本启动，仍需要确保本地后端已经运行。
