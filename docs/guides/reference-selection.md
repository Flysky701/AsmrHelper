# 声音库：识别、分段与手动选用

辅助选段展示 ASR 或通过原文语言校验的字幕片段。按起点、终点排序，保留短句、长句、重叠片段与空文本片段；没有质量排名、精选数量限制、音量候选或自动选用。试听、选用、时间调整及原文编辑仍由用户操作。

没有有效时间戳的台词列在末尾，标注“未提供有效时间戳”，不伪造起止时间；用户可在工作台手动定位。未识别到文本或关闭 ASR 时仍可手动选段。ASR 默认启用，但须点击“识别并分段”才会提交任务。字幕文件存在不代表可用：语言未知、与录音语言不一致或时间越界时继续走 ASR。

## 台词识别分数

- Faster-Whisper：辅助选段沿用当前配置的 Faster-Whisper 模型，展示引擎 `avg_logprob`（平均 token 对数概率，越接近 0 越高）。不转为百分比，不用 `no_speech_prob` 的补数代替台词置信度。辅助选段跳过旧后处理的分数过滤、短句过滤和合并。
- Fun-ASR：句级返回中明确存在 `confidence` 或 `score` 时保留原值与字段名；只有词时间戳、句级未提供分数时保持缺失，不把整段分数复制给每句。
- Qwen3-ASR：当前适配器所消费的转录与强制对齐返回没有句级置信度，保持缺失。无对齐时的整段时长回退会标记为 `whole_audio`，辅助选段不会将其当成真实句级时间戳。
- 字幕、缺失值和非有限分值显示“未提供置信度”。不同引擎原始分数不作跨引擎比较。识别元数据通过领域模型与 ASR worker 往返保留。

## 验证（2026-09-30）

使用本地假模型与合成音频，未下载或运行真实模型。

- 122 项 Python 功能回归通过，覆盖时间顺序、超过五段、重叠与短句、无评分或推荐调用、原始负分与零分、缺失置信度、无时间戳、空结果、字幕语言校验、异步任务结果。
- 57 项 ASR／字幕／运行时契约回归通过。
- 5 项前端测试通过，覆盖全部片段保留、原始分数展示、显式手动选用、选区播放边界与循环。
- TypeScript 与 Vite 构建通过。

真实耳语录音的识别准确性、模型原始分数分布及浏览器人工试听尚未验收。模型自身 VAD 与解码行为仍属于识别过程，不保证识别输出无幻觉；本功能不再据音量或启发式质量分数筛选识别后的片段。

验证命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_reference_transcript_segments.py tests/test_voice_analysis.py tests/test_audio_preprocessor_core.py tests/test_fun_asr_backend.py tests/test_fun_asr_timestamps.py tests/test_qwen3_asr_backend.py tests/test_speech_http.py tests/test_reference_analysis_dispatch.py -q
.venv/Scripts/python.exe -m pytest tests/test_runtime_isolation.py tests/test_asr_http_api.py tests/test_subtitle_domain.py tests/test_workbench_companion_subtitles.py tests/test_speech_service.py -q
# desktop 目录下
node --test --test-isolation=none tests/referenceAnalysis.test.mjs tests/referencePlayback.test.mjs
npm.cmd run build
```
