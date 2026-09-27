# AuK 在线 Demo 测试

测试日期：2026-09-24（本地时间）。仅通过腾讯官方 Hugging Face Space 页面操作，没有部署本地模型。

## 官方示例

载入网页自带 `ref.wav`，AuK Base、NFE 32、CFG 2、Seed 42，关闭 Prompt Enhancer，时长 9.95 秒。指令：

> Convert this speech to a natural breathy whisper while preserving the original speaker identity, words, and duration.

页面成功返回输出音频，播放器显示约 10 秒。该结论仅为生成成功，没有主观听评，也未校验语义、声线保留与精确时长。

临时输出链接（可能随 Space 清理而失效）：
https://tencent-auk.hf.space/gradio_api/file=/tmp/gradio/ec6608428b839027ec0d6e1654cfb7f5c08a2c742f5d2672ddf687485e45714e/audio.wav

## 本项目中文样本

用户明确授权后上传 `output/voxcpm-whisper-exploration/normal.wav` 至同一 AuK 服务。内容为“今天辛苦了。放松下来，慢慢呼吸，我会在这里陪着你。”，时长 6.88 秒。嵌入页面上传事件超时，改用页面已展示的官方独立地址后上传成功，播放器可见输入。

关闭 Prompt Enhancer、指定 6.88 秒、Seed 42：

1. Base / NFE 32 / CFG 2，中文指令要求自然气声耳语并保留内容、音色、时长：页面返回“错误”。
2. 同参数，简短英文指令 `Convert the input speech to whispered speech, preserving the original words and speaker identity.`：页面返回“错误”。
3. Flash / NFE 4 / CFG 0，保留第二次指令：页面返回“错误”。

页面没有详细错误原因，浏览器错误日志没有提供足以定位的异常。无法判定是服务、会话、输入处理还是模型推理问题，不能将失败归因为中文或音频质量。中文样本没有得到可试听的新输出，不算集成或音质验收通过。

结论：官方示例成功、本项目样本未成功。尚不能据此证明 AuK 优于 Qwen3/VoxCPM。后续需要可诊断的服务端测试或恢复后的官方服务验证。
