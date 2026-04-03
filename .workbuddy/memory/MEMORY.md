# ASMR Helper 项目长期记忆

## 项目信息
- **项目**: ASMR音频汉化工具（双语双轨处理）
- **路径**: `d:\WorkSpace\AsmrHelper\`
- **环境**: uv (.venv), PyTorch 2.11.0+cu126, PySide6 6.9.2
- **GPU**: RTX 4070 Ti SUPER (16GB)

## 项目架构
```
src/
├── core/asr/            # Faster-Whisper ASR (large-v3 默认)
├── core/tts/            # TTS: Edge-TTS / Qwen3-TTS / GPT-SoVITS
├── core/tts/qwen3_manager.py    # Qwen3 模型单例管理
├── core/tts/voice_profile.py    # 音色配置管理
├── core/vocal_separator/        # Demucs 人声分离
├── core/translate/              # DeepSeek/OpenAI 翻译
├── core/translate/terminology.py # ASMR 术语库（单例）
├── core/pipeline/__init__.py   # 统一流水线
├── core/gpu_manager.py         # GPU 资源管理（单例）
├── mixer/                      # 智能混音 + 时间轴对齐
├── gui.py                      # PySide6 GUI (1430行)
└── config.py                   # 配置管理（单例）
```

## qwen_tts 0.1.1 API（重要！）
- 模型加载: `Qwen3TTSModel.from_pretrained(path, device_map="cuda:0", dtype=torch.bfloat16)`
- 预设音色: `model.generate_custom_voice(text, speaker=..., language="chinese", instruct=...)`
- 克隆音色: `model.generate_voice_clone(text, language="chinese", voice_clone_prompt=dict)`
- 设计音色: `model.generate_voice_design(text, instruct=..., language="chinese")`
- 语言代码: `"chinese"` 不是 `"zh"`
- 返回值: `(List[np.ndarray], int)` 需手动 `sf.write()`
- **旧 API `model.generate()` 已不存在！**

## Qwen3-TTS 音色系统（report_5）
- 三类: 预设(A1-A7, CustomVoice) / 自定义(B1-B4, VoiceDesign→Clone) / 克隆(C1-Cn, Base)
- 核心类: VoiceProfile + VoiceProfileManager + Qwen3ModelManager
- 预生成方案: VoiceDesign → Base clone_prompt → 后续 clone 快速复用
- 配置: `config/voice_profiles.json`, 缓存: `models/voice_profiles/`

## 关键已完成功能
- VTT 智能跳过（中文VTT省51s, 日文VTT省23s）
- TTS 逐句时间轴对齐 (`Mixer.build_aligned_tts()`)
- 批量并行处理 + GPU 锁
- ASMR 术语库
- GUI: Edge-TTS/Qwen3-TTS Tab 切换

## 关键注意事项
- pydub 用 imageio_ffmpeg 内置版本
- Demucs `get_model()` 不接受 device 参数, 需手动 `.to(device)`
- subprocess.run 需 `encoding='utf-8', errors='replace'`
- Windows print 不能用 emoji
- Python 模块查找顺序: 当前工作目录优先于 site-packages（sox.py 教训）

## Bug 历史（重要教训）
- **sox.py 命名冲突**: 项目根目录 sox.py 导致 `import qwen_tts` 静默退出 (exit 0)
- **API 变更**: qwen_tts 0.1.1 废弃 `model.generate()`, 改用 generate_custom_voice/clone/design
- **torch_dtype 废弃**: 改用 `dtype` 参数

## 运行方式
```powershell
cd d:\WorkSpace\AsmrHelper
.\run.ps1                    # GUI
.\run.ps1 single audio.wav   # 单文件
.\run.ps1 batch "D:/ASMR"    # 批量
uv run python scripts/asmr_bilingual.py --input "audio.wav" --vtt-dir "D:/ASMR_O"
```
