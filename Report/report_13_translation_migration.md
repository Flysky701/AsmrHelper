# Report #7：翻译流程对比与迁移方案

> 作者：AI 助手
> 日期：2026-04-04
> 对比项目：VoiceTransl (GalTransl 引擎) vs AsmrHelper

---

## 一、执行摘要

本报告对 `D:\WorkSpace\VoiceTransl`（基于 GalTransl 引擎）和 `D:\WorkSpace\AsmrHelper` 两个项目的翻译流水线进行深度横向对比，分析 VoiceTransl 中成熟的翻译机制在 AsmrHelper 中的**复刻/优化**可行性，并给出分优先级的迁移建议。

核心结论：**AsmrHelper 的翻译实现目前处于"够用但脆弱"的状态**，VoiceTransl 提供了多项工程成熟度更高的机制，其中 3 项可在 2-3 天内低风险迁移，另有 2 项中期可引入以大幅提升翻译质量。

---

## 二、两项目翻译架构概览

### 2.1 VoiceTransl（GalTransl 引擎）

```
输入 SRT
  ↓  Frontend/GPT.py  → doLLMTranslateSingleFile()
  ↓  Dictionary.py    → pre_jp 预处理字典替换
  ↓  CSentense.py     → 结构化为 CSentense 对象（保留时间戳）
  ↓  Cache.py         → 缓存命中检查（按 post_jp hash）
  ↓  GPT35Translate.py / GPT4Translate.py / SakuraTranslate.py
  │    ├── 批次组装（10句/批）
  │    ├── GPT Dictionary 注入提示词
  │    ├── 温度调节重试（0.1 → 0.3）
  │    ├── Context 保留（滑动窗口）
  │    ├── 断句重试（按最后成功索引拆分）
  │    └── Degeneration 检测（仅 Sakura）
  ↓  Problem.py        → 质量检测（残日、标点、换行、长度）
  ↓  Dictionary.py    → post_zh 后处理字典替换
  ↓  输出 SRT / JSON
```

**核心数据结构** `CSentense`：
```python
{
  "index": int,        # 在批次中的序号
  "pre_jp": str,       # 原始日文（用于缓存 key）
  "post_jp": str,      # 预处理后日文（送入 LLM）
  "pre_zh": str,       # 初步译文
  "post_zh": str,      # 后处理译文（最终）
  "start": float,      # 时间戳秒
  "end": float,
  "problem": str,      # 质量问题标记
  "trans_by": str,     # 翻译来源（GPT35/GPT4/Sakura/Cache）
  "conf": float,       # GPT-4 置信度
}
```

### 2.2 AsmrHelper（现有实现）

```
输入 WAV / VTT
  ↓  Pipeline.run()  → 5步流水线
  ↓  [Step 3] Translator.translate_batch()
  │    ├── 逐条发送 API 请求（1句/请求）
  │    ├── 术语库注入 system_prompt（TerminologyDB）
  │    ├── 失败降级：保留原文（无重试）
  │    └── 固定 temperature=0.3
  ↓  写入 translated.txt
  ↓  [Step 4] TTS 时间轴对齐
```

**核心数据结构**（无专用结构，直接操作 dict 列表）：
```python
{
  "start": float,       # 来自 ASR 或 VTT
  "end": float,
  "text": str,          # 原文
  "translation": str,   # 翻译结果（直接填充）
}
```

---

## 三、逐项深度对比

### 3.1 批量翻译策略

| 维度 | VoiceTransl | AsmrHelper | 差距 |
|------|-------------|------------|------|
| 请求粒度 | 10句/批（JSON 数组） | 1句/请求 | **10x 差距** |
| 上下文利用 | 批次内多句共享上下文 | 无上下文 | 显著 |
| API 调用次数（100句） | ~10次 | 100次 | 10x 差距 |
| 响应延迟（100句） | ~30s | ~150s | ~5x 差距 |

**VoiceTransl 批量请求格式示例：**
```json
[
  {"id": 1, "name": "春花", "src": "春花さん、大丈夫ですか？"},
  {"id": 2, "name": "春花", "src": "はい、少し疲れただけです"},
  {"id": 3, "name": "旁白", "src": "春花はゆっくりと立ち上がった"}
]
```
LLM 同时看到 3 句，能感知对话逻辑并保持一致性。AsmrHelper 每句独立翻译，"はい" 可能每次翻译不同。

### 3.2 重试机制

| 维度 | VoiceTransl | AsmrHelper | 差距 |
|------|-------------|------------|------|
| 重试策略 | 温度切换(0.1→0.3)→断句重试→Context 重置 | 无重试，直接保留原文 | **严重缺失** |
| 最大重试次数 | 5次（可配置） | 0次 | 严重 |
| 失败处理 | 最终仍失败→标记"Failed translation" | 保留原文（可能送入 TTS 产出日文音频） | 严重 |
| Degeneration 检测 | Sakura 后端有（检测重复流输出） | 无 | 中等 |

**AsmrHelper 当前风险场景：**  
若 API 偶发超时，翻译失败则原文（日文）直接传入 TTS 引擎。对于 Edge-TTS（中文引擎），日文文本会产出奇怪发音；对于 Qwen3-TTS，可能输出乱音。**最终用户听到的是日文原声 + 奇怪 TTS 合音**。

### 3.3 字典系统

| 维度 | VoiceTransl | AsmrHelper | 差距 |
|------|-------------|------------|------|
| 字典类型 | 三层（pre-process / gpt-inject / post-process） | 一层（仅 system_prompt 注入） | 显著 |
| 条件字典 | 支持 `[and]`/`[or]` 多条件 | 不支持 | 中等 |
| 场景字典 | 支持对话/独白区分 | 不支持 | 中等 |
| 持久化 | JSON 文件 | JSON 文件 | 相当 |
| 动态词量 | 按上下文动态筛选相关词 | 截断前20条 | 中等 |

**VoiceTransl 三层字典的实际价值：**
- `pre_jp` 字典：在送入 LLM 前修正 OCR/ASR 错误（如「はか」→「墓」）
- `gpt_dict` 字典：注入提示词引导 LLM 使用指定翻译
- `post_zh` 字典：修正 LLM 顽固的错误翻译（如固执使用"奴隶"替换"御主人様"）

### 3.4 翻译质量检测

| 维度 | VoiceTransl | AsmrHelper | 差距 |
|------|-------------|------------|------|
| 残日检测 | ✅ 检测译文中残留假名 | ❌ 无 | 严重 |
| 标点一致性 | ✅ 检测中日标点不匹配 | ❌ 无 | 中等 |
| 换行保留 | ✅ 检测换行符丢失 | ❌ 无 | 低（ASMR 无多行字幕） |
| 长度比对 | ✅ 检测译文异常短/长 | ❌ 无 | 中等 |
| 词频异常 | ✅ 检测词汇重复度过高 | ❌ 无 | 低 |

**残日检测对 AsmrHelper 的重要性：**  
当 ASR 识别的日文文本包含说话口癖（如「えーと」「あの」），或遇到生僻语法，LLM 有时会保留部分假名在译文中（如"真的はい呢"）。这类错误无法被发现，会直接传入 TTS，产出带日文音节的中文语音。

### 3.5 翻译缓存

| 维度 | VoiceTransl | AsmrHelper | 差距 |
|------|-------------|------------|------|
| 翻译缓存 | ✅ Cache.py，按 post_jp hash | ❌ 无（skip_existing 仅跳过整体步骤） | 显著 |
| 增量重处理 | ✅ 只翻译新增/变更句子 | ❌ 每次全量翻译 | 显著 |
| 重试失败项 | ✅ 可单独重试标记为失败的条目 | ❌ 不支持 | 中等 |

**缓存的实际价值场景：**  
同一音声作品常有 DLC/续集复用台词。若 200 句中有 60 句相同，缓存可节省 60 次 API 调用（约节省 40% 费用）。

### 3.6 上下文管理（对话连贯性）

| 维度 | VoiceTransl | AsmrHelper | 差距 |
|------|-------------|------------|------|
| 对话历史 | ✅ 滑动窗口（4条之前翻译） | ❌ 无状态 | 严重 |
| 对话检测 | ✅ 解析「」『』引号 | ❌ 无 | 中等 |
| 说话人识别 | ✅ 从 SRT 格式提取 | ❌ 无（ASMR 通常单说话人） | 低 |

**无状态翻译的典型问题：**
- 称呼不一致：同一人物在不同句子被翻译为"主人""大人""您"三种称呼
- 代词漂移："她"/"她的""你的"指向在无上下文情况下容易混乱
- 情感断层：上句是疑问语气，下句是回答，无上下文 LLM 无法感知

---

## 四、迁移可行性分析

### 4.1 可直接迁移（低风险，1-3 天）

#### M1：批量翻译（10 句/批）

**可行性：** 高。AsmrHelper 已有 `translate_batch()` 接口，修改为批量 JSON 格式发送即可。

**改造点：**
```python
# 现有：逐条发送
for text in texts:
    response = client.chat.completions.create(messages=[..., {"role": "user", "content": text}])

# 改造后：批量发送
batch_prompt = json.dumps([{"id": i, "src": t} for i, t in enumerate(batch)])
response = client.chat.completions.create(messages=[..., {"role": "user", "content": batch_prompt}])
results = json.loads(response.choices[0].message.content)
```

**预期收益：** API 调用次数降低 10x，翻译速度提升 3-5x（批次构建+解析有少量开销）。

**风险：** LLM 有时不严格遵循 JSON 格式输出，需要增加 JSON 解析容错逻辑。

---

#### M2：简单重试机制（温度切换 + 指数退避）

**可行性：** 高。在 `translate_batch()` 中增加 try/except + 重试循环即可。

**改造方案：**
```python
def translate_batch(self, texts, ..., max_retries=3):
    for attempt in range(max_retries):
        try:
            temperature = 0.1 if attempt == 0 else 0.3
            response = client.chat.completions.create(..., temperature=temperature)
            return parse_response(response)
        except Exception as e:
            if attempt == max_retries - 1:
                return [text for text in texts]  # 最终降级：原文
            time.sleep(2 ** attempt)  # 指数退避：1s, 2s, 4s
```

**预期收益：** 消除因 API 偶发超时导致的"日文混入 TTS"问题。

**风险：** 极低。纯逻辑修改，不影响现有接口。

---

#### M3：残日检测（Post-translation QA）

**可行性：** 高。独立函数，可在 `translate_batch()` 返回后调用。

**改造方案：**
```python
def _has_japanese_residue(text: str) -> bool:
    """检测译文中是否残留日文假名"""
    import re
    kana = re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text)
    return len(kana) > 2  # 允许少量（如 ASMR 音效词）

def translate_batch(self, texts, ...):
    results = _call_api(texts)
    # 质量检测
    for i, (orig, trans) in enumerate(zip(texts, results)):
        if _has_japanese_residue(trans):
            logger.warning(f"[QA] 第{i}句残留日文: {trans[:50]}")
            results[i] = orig  # 降级保留原文，或触发重译
    return results
```

**预期收益：** 在混音前发现并处理残日问题，避免产出带日文音节的 TTS。

---

### 4.2 需适配后迁移（中风险，3-7 天）

#### M4：翻译缓存层

**可行性：** 中。需要新建 `TranslationCache` 类，管理缓存文件。

**设计草图：**
```python
class TranslationCache:
    """翻译缓存（按 MD5(原文) → 译文 映射）"""
    
    def __init__(self, cache_dir: Path):
        self.cache_file = cache_dir / "translation_cache.json"
        self._cache = self._load()
    
    def get(self, text: str) -> Optional[str]:
        key = hashlib.md5(text.encode()).hexdigest()
        return self._cache.get(key)
    
    def set(self, text: str, translation: str):
        key = hashlib.md5(text.encode()).hexdigest()
        self._cache[key] = translation
        self._save()
```

**与现有代码集成点：**  
在 `Pipeline.run()` Step 3 之前，先过一遍缓存检查，命中的跳过，未命中的收集为新批次发送。

**预期收益：** 同作品批量处理时节省 20-60% API 费用；重处理单文件时跳过已翻译句子。

**适配成本：** 中等。需考虑缓存 key 策略（是否包含上下文）、过期策略、存储位置。

---

#### M5：三层字典系统

**可行性：** 中。现有 `TerminologyDB` 可扩展为三层。

**设计草图（扩展现有 TerminologyDB）：**
```python
class EnhancedTerminologyDB(TerminologyDB):
    """三层字典：预处理 / GPT注入 / 后处理"""
    
    def preprocess(self, text: str) -> str:
        """ASR纠错字典：在送入LLM前替换"""
        for src, dst in self._pre_terms.items():
            text = text.replace(src, dst)
        return text
    
    def build_gpt_dict_prompt(self, text: str) -> str:
        """GPT字典：只注入与当前批次相关的术语"""
        relevant = {k: v for k, v in self._gpt_terms.items() if k in text}
        if not relevant:
            return ""
        return "术语约束：\n" + "\n".join(f"{k}={v}" for k, v in relevant.items())
    
    def postprocess(self, text: str) -> str:
        """后处理字典：修正LLM顽固错误"""
        for src, dst in self._post_terms.items():
            text = text.replace(src, dst)
        return text
```

**与现有代码集成点：**  
- `preprocess()` 在 Step 3 文本送入 `translate_batch()` 之前调用
- `build_gpt_dict_prompt()` 注入 system_prompt
- `postprocess()` 在 `translate_batch()` 返回后调用

**预期收益：** 显著提升常见角色称谓、ASMR 专用词汇的翻译一致性。

---

### 4.3 不建议迁移（高成本 / 低收益）

#### 不迁移：对话检测与说话人识别

**原因：** ASMR 音声内容几乎全为**单一说话人独白**，对话检测（解析「」『』）的价值极低。VoiceTransl 针对视觉小说/动漫（多角色对话）设计，其对话分析逻辑与 ASMR 使用场景不符。

#### 不迁移：Degeneration 检测

**原因：** Degeneration（LLM 输出陷入重复循环）是本地推理模型（Sakura/Qwen-local 4-bit 量化）的专有问题，AsmrHelper 使用云端 API（DeepSeek/OpenAI），此问题不存在。

#### 不迁移：JSONL 置信度 + Proofreading 模式

**原因：** GPT-4 的 `conf/doub/unkn` 字段用于游戏本地化质量管控，需要人工审核流程配合。ASMR 汉化是全自动流水线，无人工审核节点，此功能无意义。

---

## 五、迁移优先级路线图

```
Phase 1（1-2 天，零风险）
├── M1: 批量翻译（10句/批）    ← 最高优先级，收益最大
├── M2: 重试机制（温度切换）    ← 消除"日文入侵 TTS"风险
└── M3: 残日质量检测           ← 防御性措施，独立函数

Phase 2（3-5 天，低风险）
├── M4: 翻译缓存层             ← 节省 API 费用，提升增量处理速度
└── M5: 三层字典扩展           ← 提升翻译一致性

Phase 3（可选，长期）
└── 上下文窗口（4句滑动）      ← 提升 ASMR 长句连贯性，需验证收益
```

---

## 六、代码改造蓝图

### 6.1 改造后的翻译模块结构

```
src/core/translate/
├── __init__.py          # Translator 类（主入口，接口不变）
├── terminology.py       # TerminologyDB（升级为三层）
├── batch.py             # BatchTranslator（新建：批量+重试逻辑）
├── cache.py             # TranslationCache（新建：翻译缓存）
└── quality.py           # QualityChecker（新建：残日/质量检测）
```

### 6.2 改造后的 Translator 调用链

```python
class Translator:
    def translate_batch(self, texts, ...):
        # 1. 预处理字典替换
        texts = [self.term_db.preprocess(t) for t in texts]
        
        # 2. 缓存命中检查
        cache_hits = [self.cache.get(t) for t in texts]
        uncached = [(i, t) for i, (t, h) in enumerate(zip(texts, cache_hits)) if h is None]
        
        # 3. 批量翻译（带重试）
        if uncached:
            new_results = self._translate_with_retry(
                [t for _, t in uncached],
                gpt_dict=self.term_db.build_gpt_dict_prompt(" ".join(texts))
            )
            for (i, orig), trans in zip(uncached, new_results):
                cache_hits[i] = trans
                self.cache.set(orig, trans)
        
        # 4. 质量检测
        results = [h or orig for h, orig in zip(cache_hits, texts)]
        results = self.quality_checker.filter(results, texts)
        
        # 5. 后处理字典替换
        results = [self.term_db.postprocess(r) for r in results]
        
        return results
```

### 6.3 迁移的关键设计原则

1. **接口不变原则**：`Translator.translate_batch(texts)` 签名保持不变，内部升级对上层 Pipeline 透明
2. **渐进式启用**：每个新机制（缓存/重试/QA）通过 Config 开关控制，默认关闭，稳定后开启
3. **ASMR 特化**：不照搬 GalTransl 的全部功能，只迁移对 ASMR 场景有价值的子集

---

## 七、风险评估

| 风险 | 描述 | 缓解措施 |
|------|------|----------|
| 批量 JSON 解析失败 | LLM 不遵循 JSON 格式 | 增加 fallback：解析失败时降级为逐条翻译 |
| 缓存 key 碰撞 | 相似日文映射到同一译文 | 使用完整文本 MD5 而非截断 |
| 重试放大 API 费用 | 频繁重试消耗 token | 限制最大重试次数为 3，加指数退避 |
| 三层字典冲突 | pre/gpt/post 字典互相干扰 | 字典分文件存储，加载顺序明确，前面层只替换原文词汇 |

---

## 八、总结

| 对比维度 | VoiceTransl | AsmrHelper（现状） | AsmrHelper（迁移后预期） |
|----------|-------------|-------------------|------------------------|
| 翻译速度（100句） | ~30s | ~150s | ~35s（+5%开销） |
| API 调用次数 | ~10次 | 100次 | ~10次 |
| 翻译连贯性 | 高（批次上下文） | 低（无状态） | 中（批次上下文） |
| 失败鲁棒性 | 高（多级重试） | 低（无重试） | 高（重试+降级） |
| 翻译一致性 | 高（三层字典） | 中（单层字典） | 高（三层字典） |
| 质量保障 | 有（残日/标点检测） | 无 | 有（残日检测） |
| 增量翻译 | 有（翻译缓存） | 无 | 有（翻译缓存） |
| 工程复杂度 | 高（专为游戏本地化） | 低（适配 ASMR） | 中（ASMR 定制化） |

VoiceTransl 的翻译引擎为**游戏文本本地化**场景设计，具备更完整的质量管控体系。AsmrHelper 的翻译模块当前是"最小可用"状态——能跑通，但缺少容错保障。通过选择性迁移 VoiceTransl 的三项核心机制（批量翻译、重试逻辑、质量检测），可在保持 ASMR 定制化特性的同时，将翻译模块的工程成熟度大幅提升，同时降低 API 成本约 90%。

---

*本报告为 AsmrHelper 架构分析系列第 7 篇，前序报告详见 Report/ 目录。*
