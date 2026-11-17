# 许可范围与第三方声明

本项目的 `CC-BY-NC-4.0` 许可仅涵盖维护者有权授权的原创内容。第三方软件、依赖、运行时、模型权重和外部素材不改用此许可；必须保留其原有许可证、版权、署名和其他声明。本文件是范围说明，不替代各组件的许可证或构成完整合规认证。

## 第三方组件

- Python、uv、Python 包、Rust crates、npm 依赖和原生组件依各自许可证分发。版本以 `uv.lock`、`desktop/src-tauri/Cargo.lock` 和 `desktop/package-lock.json` 为准；其中第三方包的许可字段保持原样。
- Windows 打包流程保留原始许可证，并在 `backend/licenses/` 中收集清单、Python/native、Rust 和 npm 声明。FFmpeg 的许可证及构建/源码信息仍位于 `backend/ffmpeg/LICENSE` 和 `backend/ffmpeg/README.txt`。根目录项目许可不覆盖这些组件。
- 当前 Windows 构建使用 Gyan 的 FFmpeg 8.1.2 GPL v3 构建。应用通过独立进程调用 `ffmpeg`/`ffprobe`；FFmpeg 及其随附 DLL 继续受原许可证约束，分发者仍须满足适用的 GPL 源码提供等义务。
- `audio` 可选依赖中的 `pytsmod 0.3.8` 声明 GPL-3.0，不能改为 CC-BY-NC-4.0。当前源码没有导入或调用它，基础安装包不包含该可选依赖。若以后将 GPL 组件与应用组合或直接集成，须先核查兼容性；不能把非商业限制加到 GPL 组件上。
- 模型权重未随基础安装包分发；按需下载的模型与外部服务须遵守各自许可及服务条款。本项目不替用户授权输入音频、声音、字幕或其他素材，也不因工具许可自动赋予或限制输出素材的权利。

## 既有版本与许可全文

此前项目 README 和 Python 元数据声明 MIT，但仓库没有根目录 MIT 许可全文。本次变更不撤销以前已授出的权利，也不重写历史。已发布的 `v1.0.0` 标签及既有安装包仍对应 `d54affdaa9974822b40e22e25e626b686d9e8862`，不因当前源码改许可而被重新许可或替换。

项目 [LICENSE](LICENSE) 使用未修改的 [CC 官方英文法律文本](https://creativecommons.org/licenses/by-nc/4.0/legalcode.txt)，从 Creative Commons 官方 `cc-legal-tools-data` 仓库的 [`docs/licenses/by-nc/4.0/legalcode.txt`](https://github.com/creativecommons/cc-legal-tools-data/blob/a0dac18d1a773b4cdb7d8dd5d9bf4efab7901030/docs/licenses/by-nc/4.0/legalcode.txt) 获取。标准标识为 [`CC-BY-NC-4.0`](https://spdx.org/licenses/CC-BY-NC-4.0.html)。
