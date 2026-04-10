# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20250409-001] best_practice

**Logged**: 2026-04-09T20:03:00+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
试音功能生成600秒超长音频的问题 - ref_text prompt注入导致

### Details
**问题现象**: 克隆音色试音功能合成了600秒的超长音频

**根本原因**: 
1. `ref_text` 参数没有长度限制，可能包含超长文本（多个字幕片段拼接）
2. 超长 `ref_text` 被直接传入 `create_voice_clone_prompt()`，导致模型生成异常长音频

**涉及代码位置**:
- `src/core/tts/voice_designer.py:344-347` - `clone_and_preview()` 中 `ref_text` 直接传入
- `src/core/tts/audio_preprocessor.py:879` - `_build_ref_text()` 返回所有片段文本拼接

**修复方案**:
1. 在 `audio_preprocessor.py` 添加 `REF_TEXT_MAX_LENGTH = 500` 常量
2. 在 `_build_ref_text()` 方法中截断超长文本并打印警告
3. 在 `voice_designer.py` 的 `clone_and_preview()` 和 `clone_from_audio()` 入口添加长度检查

### Suggested Action
- 所有涉及 `ref_text` 或 `prompt` 的接口都应添加长度限制
- 考虑在模型调用层统一添加防护

### Metadata
- Source: user_feedback
- Related Files: 
  - src/core/tts/voice_designer.py
  - src/core/tts/audio_preprocessor.py
- Tags: prompt-injection, tts, voice-clone, safety
- Pattern-Key: harden.input_validation

---

## [LRN-20250409-003] knowledge_gap

**Logged**: 2026-04-09T20:17:00+08:00
**Priority**: medium
**Status**: pending
**Area**: backend

### Summary
历史功能残留：中文发音提示词注入方案（已删除但需关注）

### Details
**背景**: 
- 为解决日语克隆音色发中文时发音不佳的问题（日语元音只有5个），曾尝试在 `ref_text` 中注入中文发音提示词
- 提示词内容：`"注意：翘舌音 zh/ch/sh/r 要卷舌，元音 ü 要圆润，儿化音要轻巧。"`

**实现** (提交 8d4e87b, 4月7日):
- 添加了 `CHINESE_PRONUNCIATION_HINTS` 常量
- 添加了 `_inject_pronunciation_hints()` 函数
- 在 `clone_from_audio()` 中将提示词附加到 `ref_text`

**当前状态**:
- 该功能已在后续提交中删除
- 但可能存在的残留影响：
  1. 之前生成的 `prompt_cache` (.pt 文件) 可能仍包含注入的提示词影响
  2. 需要验证是否完全清理干净

**相关提交**:
- 添加: `8d4e87b` - "feat(voice_clone): 方案2 - 注入中文发音提示词到 ref_text"
- 删除: 后续提交（已删除相关代码）

### Suggested Action
- [ ] 检查已生成的 `.pt` 文件是否需要重新生成
- [ ] 验证克隆音色试听是否仍受此提示词影响
- [ ] 如问题仍存在，需深入调查残留位置

### Metadata
- Source: user_feedback
- Related Files: 
  - src/core/tts/voice_designer.py
- Tags: voice-clone, japanese, pronunciation, historical-issue
- See Also: LRN-20250409-001

---

## [LRN-20250409-002] insight

**Logged**: 2026-04-09T20:03:00+08:00
**Priority**: medium
**Status**: pending
**Area**: backend

### Summary
Qwen3-TTS 模型参数 `ref_text` 会显著影响生成音频长度

### Details
`ref_text` 不仅是参考音频的文本标注，还会直接影响模型生成音频的时长。
- 当 `ref_text` 过长时，模型可能产生异常长的输出
- 这与一般的 TTS 模型行为不同，需要特别注意

### Suggested Action
- 文档化此行为
- 在 UI 层提示用户 ref_text 长度限制

### Metadata
- Source: error
- Related Files: src/core/tts/voice_designer.py
- Tags: qwen3-tts, model-behavior

---
