# 当前电脑运行环境检查

检查日期：2026-09-14。项目：`D:\WorkSpace\AsmrHelper`。

## 结论

基础桌面启动、HTTP API、音频转换和默认 Edge TTS 已通过实机检查。高级引擎尚未全部就绪；本次没有执行完整音频汉化流水线，也没有调用付费翻译 API。

## 实测结果

| 项目 | 结果 |
| --- | --- |
| 项目 Python | 3.12.14，基础依赖导入通过，API 注册 92 个路由 |
| 自动测试 | 414 passed，18.34 秒 |
| 前端 | 项目内 Node 24.19.0，TypeScript / Vite production build 成功 |
| 桌面 | GNU Rust 1.98.0 + 项目内 LLVM-MinGW，release 构建成功 |
| 默认启动器 | GUIRun.bat 启动新 release 和 8000 端口后端；桌面发出的能力、预设、任务、音色请求均返回 200 |
| HTTP 独立启动 | 18000 端口健康检查、OpenAPI、任务、Edge 能力接口均返回 200 |
| 音频 | SoundFile 写入/读取 WAV 成功；FFmpeg 7.1 转 MP3 成功 |
| 默认 TTS | Edge TTS 实际生成中文测试 MP3 成功 |
| 翻译配置 | DeepSeek 密钥已配置，仅检查存在性，未验证服务端有效性 |
| GPU | RTX 5070 Laptop，8151 MiB，驱动 591.91 |
| 主环境 PyTorch | 2.13.0+cpu；本地基础音频处理使用 CPU |

## 修复

- GUIRun.bat 自动识别项目内 Node/npm、Cargo、Rustup 和 GNU/LLVM-MinGW 工具链，避免依赖旧电脑 PATH 或缺失的 MSVC link.exe。
- release 启动只构建应用可执行文件，不额外制作安装包。
- setup.ps1 同样识别项目内完整 Node/npm 安装。
- 重新生成 `desktop/src-tauri/target/release/asmr-helper.exe`，替换落后于源码的构建产物。

## 未通过或未验收项

- Faster-Whisper 各模型和 Demucs 的资源检查通过；未进行真实模型推理。
- Qwen ASR 导入首次耗时约 266 秒，预热后资源检查通过；其 PyTorch 为 CPU 版本。
- Qwen TTS 使用 PyTorch 2.10.0+cu128，CUDA 检测通过，完整导入约 244 秒；资源探测的 30 秒超时仍触发，并提示缺少 SoX，未执行合成验收。
- Fun-ASR、VoxCPM2 模型存在，但运行依赖未就绪；Fun-ASR VAD 和 Qwen forced aligner 模型缺失。
- Git 检测到仓库属于旧 Windows SID。本次只通过命令级 safe.directory 读取状态，未修改全局 Git 配置。
- 沙箱最初拒绝写入测试目录、构建缓存及用户状态目录；正常用户权限复核通过。

验证日志和短音频位于 `logs/runtime-check-20260914/`。原有 `profiles.py`、`test_runtime_isolation.py` 修改已保留。
