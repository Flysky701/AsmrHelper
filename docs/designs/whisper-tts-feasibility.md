# 耳语 TTS 探索（历史）

调研、旧路径分析及当时验收完整保留在 [历史归档](../archived/designs/whisper-tts-feasibility.md)。当前能力以 [统一 TTS 指南](../guides/tts.md) 为准。`scripts/probe_whisper_tts.py` 已迁移为项目解释器调用 Speech 编译与隔离 Worker，不再走旧 Registry，也不承诺固定随机种子或报告主进程 GPU 峰值。
