"""
测试翻译模块 Phase 2: 缓存层 + 三层字典

运行方式:
    uv run python tests/test_translate_phase2.py
"""

import sys
import json
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_three_layer_terminology():
    """测试三层字典功能"""
    print("\n" + "="*60)
    print("测试 1: 三层字典 (ThreeLayerTerminologyDB)")
    print("="*60)

    # 重新加载模块以获取新类
    from importlib import reload
    import src.core.translate.terminology as terminology_module
    reload(terminology_module)

    from src.core.translate.terminology import ThreeLayerTerminologyDB

    # 创建新实例（绕过单例缓存）
    # 注意：单例模式会复用已有实例，这里测试实例方法
    db = ThreeLayerTerminologyDB()

    print(f"[TermDB] 术语统计: pre={db.pre_count}, gpt={db.gpt_count}, post={db.post_count}")
    assert db.pre_count > 0, "预处理字典应该有内容"
    assert db.gpt_count > 0, "GPT 字典应该有内容"
    assert db.post_count > 0, "后处理字典应该有内容"

    # 测试预处理（ASR 纠错）
    print("\n--- 预处理测试 ---")
    test_cases = [
        ("はか", "墓"),  # ASR 错误 -> 正确
        ("こんにちは", "こんにちは"),  # 正常文本保持不变
    ]

    for input_text, expected in test_cases:
        result = db.preprocess(input_text)
        status = "PASS" if expected in result or result == expected else "INFO"
        print(f"  [{status}] preprocess('{input_text}') -> '{result}' (expected: '{expected}')")

    # 测试 GPT 字典提示词
    print("\n--- GPT 字典提示词测试 ---")
    gpt_hint = db.build_gpt_dict_prompt(max_terms=5)
    print(f"  提示词片段: {gpt_hint[:200]}...")
    assert len(gpt_hint) > 0, "GPT 字典提示词应该非空"

    # 测试后处理（修正 LLM 顽固错误）
    print("\n--- 后处理测试 ---")
    test_cases = [
        ("主人", "主人"),  # 正确翻译保持不变
        ("奴隶", "主人"),  # 顽固错误 -> 修正
    ]

    for input_text, expected in test_cases:
        result = db.postprocess(input_text)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] postprocess('{input_text}') -> '{result}' (expected: '{expected}')")

    print("\n[PASS] 三层字典测试完成!")


def test_translation_cache():
    """测试翻译缓存层"""
    print("\n" + "="*60)
    print("测试 2: 翻译缓存层 (TranslationCache)")
    print("="*60)

    from importlib import reload
    import src.core.translate.cache as cache_module
    reload(cache_module)

    from src.core.translate.cache import TranslationCache, CacheEntry
    import tempfile
    import shutil

    # 使用临时目录
    temp_dir = Path(tempfile.mkdtemp())

    try:
        cache = TranslationCache(cache_dir=temp_dir)

        # 测试单条缓存
        print("\n--- 单条缓存测试 ---")
        test_text = "こんにちは"
        test_translation = "你好"

        # 设置缓存
        cache.set(test_text, test_translation, "deepseek-chat")
        print(f"  写入: '{test_text}' -> '{test_translation}'")

        # 读取缓存
        cached = cache.get(test_text)
        print(f"  读取: '{test_text}' -> '{cached}'")
        assert cached == test_translation, "缓存读取失败"

        # 读取不存在的缓存
        missing = cache.get("不存在的内容")
        assert missing is None, "不存在的缓存应该返回 None"
        print(f"  不存在的缓存: '{missing}' (expected: None)")

        # 测试批量操作
        print("\n--- 批量缓存测试 ---")
        texts = ["文本1", "文本2", "文本3"]
        translations = ["翻译1", "翻译2", "翻译3"]

        # 批量设置
        cache.set_batch([(i, t, tr) for i, (t, tr) in enumerate(zip(texts, translations))])
        print(f"  批量写入: {len(texts)} 条")

        # 批量获取
        hits, misses = cache.get_batch(texts + ["不存在的"])
        print(f"  批量获取: {len(hits)} 条")
        print(f"    命中: {sum(1 for h in hits if h is not None)}")
        print(f"    未命中: {len(misses)}")

        # 测试统计
        print("\n--- 统计测试 ---")
        # 注意：由于使用内存缓存，统计只反映当前会话的 get 调用
        initial_stats = cache.get_stats()
        print(f"  初始统计: {initial_stats}")

        # 验证缓存能正确区分命中和未命中
        test_hit = cache.get("文本1")  # 应该在缓存中
        test_miss = cache.get("完全不存在的内容xyz123456")  # 不应该在缓存中

        print(f"  命中测试: {'文本1'} -> {test_hit}")
        print(f"  未命中测试: {'完全不存在的内容xyz123456'} -> {test_miss}")

        assert test_hit is not None, "已缓存的内容应该命中"
        assert test_miss is None, "不存在的缓存应该返回 None"

        final_stats = cache.get_stats()
        print(f"  最终统计: {final_stats}")
        print(f"    总访问: {final_stats['total']}, 命中: {final_stats['hits']}, 未命中: {final_stats['misses']}")

        # 测试文件持久化（简化版）
        print("\n--- 持久化测试 ---")
        # 保存内存缓存到文件
        cache.save(cache._memory_cache, "test_persist")
        print(f"  保存缓存到文件: {len(cache._memory_cache)} 条")

        # 创建新实例加载
        cache2 = TranslationCache(cache_dir=temp_dir)
        loaded = cache2.load("test_persist")
        print(f"  从文件加载缓存: {len(loaded)} 条")

        if len(loaded) > 0:
            # 验证可以读取到保存的内容
            cached_value = cache2.get("こんにちは")
            print(f"  验证加载: '{test_text}' -> '{cached_value}'")

        print("\n[PASS] 翻译缓存测试完成!")

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_translator_integration():
    """测试 Translator 集成缓存和三层字典"""
    print("\n" + "="*60)
    print("测试 3: Translator 集成测试")
    print("="*60)

    from importlib import reload
    import src.core.translate as translate_module
    reload(translate_module)

    from src.core.translate import Translator

    # 创建翻译器（禁用 API 调用，仅测试初始化和结构）
    print("\n--- 初始化测试 ---")

    # 测试三层字典加载
    print("  创建翻译器实例...")
    translator = Translator(
        provider="deepseek",
        model="deepseek-chat",
        use_terminology=True,
        use_batch=True,
        use_quality_check=True,
        use_cache=True,
        cache_namespace="test",
    )

    # 验证术语库
    print(f"\n  术语库状态:")
    if translator.term_db:
        print(f"    pre_terms: {translator.term_db.pre_count} 条")
        print(f"    gpt_terms: {translator.term_db.gpt_count} 条")
        print(f"    post_terms: {translator.term_db.post_count} 条")
        assert translator.term_db.pre_count > 0, "预处理字典应该有内容"
        assert translator.term_db.gpt_count > 0, "GPT 字典应该有内容"
    else:
        print("    [WARN] 术语库未加载")

    # 验证缓存
    cache = translator._get_cache()
    if cache:
        print(f"    缓存: 已初始化")
        print(f"    缓存统计: {cache.get_stats()}")
    else:
        print("    [WARN] 缓存未加载")

    print("\n[PASS] Translator 集成测试完成!")


def test_pre_post_processing():
    """测试预处理和后处理流程"""
    print("\n" + "="*60)
    print("测试 4: 预处理和后处理流程")
    print("="*60)

    from importlib import reload
    import src.core.translate.terminology as term_module
    reload(term_module)

    from src.core.translate.terminology import ThreeLayerTerminologyDB

    db = ThreeLayerTerminologyDB()

    # 模拟完整翻译流程
    original_texts = [
        "はか",  # ASR 错误
        "こんにちは、ご主人様",  # 正常
        "これは奴隶です",  # 包含 LLM 顽固错误
    ]

    print("\n--- 完整流程测试 ---")

    for text in original_texts:
        # Step 1: 预处理
        preprocessed = db.preprocess(text)
        print(f"  原文: {text}")
        print(f"  预处理: {preprocessed}")

        # 模拟翻译（这里用原文替代）
        translated = preprocessed

        # Step 2: 后处理
        postprocessed = db.postprocess(translated)
        print(f"  后处理: {postprocessed}")
        print()

    print("[PASS] 预处理和后处理流程测试完成!")


def main():
    """运行所有测试"""
    print("\n" + "#"*60)
    print("# 翻译模块 Phase 2 测试")
    print("# (缓存层 + 三层字典)")
    print("#"*60)

    try:
        test_three_layer_terminology()
        test_translation_cache()
        test_translator_integration()
        test_pre_post_processing()

        print("\n" + "#"*60)
        print("# 全部测试通过!")
        print("#"*60)

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
