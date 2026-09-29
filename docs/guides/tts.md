# TTS：能力、连接与执行

本页是当前 TTS 的唯一入口。声音库的录音编辑与音色规则交互见 [声音库与音色生成规则](voice-lab-v2.md)；任务生命周期见 [任务执行契约](../contracts/task-execution-v1.md)。历史设计、协议探测和验收记录仅用于追溯，不定义当前参数。

## 能力来源

`src/core/speech/providers.py` 的 Speech Provider 声明是唯一能力来源，`GET /api/v1/speech/providers` 对外提供引擎、模型、声音来源及参数约束。桌面和命令行均使用该目录。通用 `/capabilities` 的 TTS 输出如被兼容调用方使用，只是该目录的转换结果，不另行定义模型或默认值。

不要根据某个引擎支持克隆就推断所有模型都支持克隆，也不要从“接口兼容”推断服务接受任意模型、音色或指令。可用参数取决于具体 Provider 和模型；外部账号权限及真实可用性仍需实际验证。

## 配置与使用

外部语音服务在“引擎与资源 → 外部服务”保存为命名连接，管理服务地址和凭据。声音库管理克隆参考录音；我的音色保存可复用生成规则。三者独立管理，通过标识引用，不要求配置服务时先创建规则。

正式配音先选择引擎、模型和声音来源；保存的规则是可选项。支持默认声音的引擎可直接使用预设或默认模式，需要参考录音、描述或服务端音色 ID 的引擎必须提供相应输入。配置检查只表示字段满足约束，不等于真实合成成功。

新任务从命名连接、规则或明确提交的引擎配置生成 Speech 快照，不从旧全局 `tts` / `external_tts` 配置选择服务或声音。快照固定配方、编译器版本和非敏感连接信息；凭据单独解析，不进入公开任务数据。任务恢复核验快照和已完成音频，不因修改默认设置而悄悄重生成已完成配音。

## 有效执行入口

| 调用方 | 路径与责任 |
| --- | --- |
| 工作台单任务、批次 | Pipeline TTS 阶段使用 SpeechService；按字幕逐句生成、适配时长并组装 |
| 音色试听 | `/speech/experiments/{id}/generate` 创建 `speech.generate` 后台任务 |
| 命令行 `tts` | 使用 Speech 编译和执行；命令参数只转换显式输入，不维护另一套能力规则 |
| 本地引擎 Worker | Speech Provider 选择隔离运行环境，Worker 执行实际模型推理 |

旧 `/tts/*`、`/voice/*` HTTP 接口不恢复。底层模型适配、音频处理和隔离环境不是重复业务入口，保留供 Speech 使用。

命令行使用文本文件：

```powershell
python -m src.cli tts --input dialogue.txt --output speech.wav
python -m src.cli tts --input dialogue.txt --output speech.wav --engine edge --voice zh-CN-XiaoxiaoNeural
python -m src.cli tts --input dialogue.txt --output speech.wav --connection CONNECTION_ID --model MODEL_ID --voice VOICE_ID
python -m src.cli tts --input dialogue.txt --output speech.wav --recipe RECIPE_ID
python -m src.cli tts --help
```

标识必须替换为实际保存的连接或规则。未选连接或规则且未指定引擎时使用 Edge；明确选中连接或规则时，不用该默认值覆盖其引擎。不能可靠转换的旧参数应报出明确原因，不静默换声音。

完整处理命令 `pipeline` 对应提供 `--tts-engine`、`--tts-model`、`--tts-voice`、`--tts-connection`、`--speech-recipe`；它和单独 `tts` 命令通过同一入口构建 Speech 阶段。查看 `python -m src.cli pipeline --help` 确认输入输出与非 TTS 选项。

本地耳语探测使用项目解释器运行 `scripts/probe_whisper_tts.py --output <独立输出目录>`。脚本通过同一编译器和执行器生成普通、轻声、耳语样本，模型推理仍在隔离 Worker 中；没有模型或依赖时应报告失败。它不保证固定随机种子，不将主进程内存当作 Worker 显存，也不替代正式桌面流程验收。

## 数据归属与历史

连接、凭据、参考录音、规则及实验索引位于 `config/voice_lab/`，不要分享整个目录。正式配音音频继续保存在所属任务中：`tts_output.wav` 同级的 `speech/<实验ID>/audio`、`aligned`、`assemblies`。独立试听保持自己的目录；已有历史音频不迁移。

旧配置只作为迁移输入保存，不覆盖现有连接，不自动猜测协议、模型、声音或文本对应关系。历史记录可继续读取；能够恢复的历史任务还必须通过原快照、凭据引用与音频完整性检查。无法可靠转换的旧数据保留并记录原因，不能用新默认值冒充迁移成功。

### 显式导入旧连接

使用运行中的本地服务，先 `GET /api/v1/speech/legacy-import` 查看脱敏预览，再 `POST /api/v1/speech/legacy-import` 执行增量导入。导入只新增可明确映射的命名连接，不切换默认项，不创建或猜测音色规则，不修改旧配置。报告列出保留的模型、音色、指令等字段及无法转换项；使用前按服务实际能力核对。导入账本防止重复导入覆盖当前连接。此工具不调用远端合成服务。

回退时保留旧配置作为原始来源，停止选择本次新增连接即可恢复原有命名连接的使用；不要删除被历史任务引用的凭据或连接。代码回退使用本轮分批提交的逆向提交，先保存本轮之后的新变更。导入不进行破坏性覆盖，无需用旧文件覆盖整个 `voice_lab` 目录。

## 开发边界

1. 新能力只在 Speech Provider 声明，模型安装及依赖继续登记在 `config/models.yaml`，避免混淆运行能力与资源下载信息。
2. 合成请求通过 Speech 编译器转换为引擎请求，后端再次校验支持的声音来源、模型和参数。新增调用方复用该路径。
3. 凭据属于命名连接；不得在旧全局设置、桌面常量或 CLI 中新增第二份默认规则。
4. 兼容转换只接受范围明确的旧输入；旧标识可以映射，无法确认语义的值不能猜测。
5. 模拟响应测试验证协议、快照和恢复；真实模型/外部服务验收验证依赖、权限和实际音频，两者分别记录。构建成功不等于合成成功。

本轮清理及验证证据见 [交付记录](../roadmap/tts-unification-delivery-2026-09-30.md)；本页不把历史模型验收当成本轮真实推理证据。
