"""测试 ASR 后处理模块"""

import sys
sys.path.insert(0, "d:/WorkSpace/AsmrHelper/src")

from core.asr.postprocess import ASRPostProcessor, PostProcessConfig, postprocess_segments


def test_normalization():
    """测试文本规范化"""
    print("\n=== 测试文本规范化 ===")

    processor = ASRPostProcessor()

    test_cases = [
        # (原始文本, 预期结果)
        ("こんにちは。。。", "こんにちは..."),  # 重复句号 → 省略号
        ("はい！！！", "はい!"),              # 重复感叹号 → 半角单感叹号
        ("え？？？", "え?"),                  # 重复问号 → 半角单问号
        ("こんにちは。　　 world", "こんにちは.world"),  # 全角句号转半角 + 空格处理
        ("[音楽] こんにちは [掌声]", "こんにちは"),  # 幻觉标记
        ("（英語）こんにちは", "（英語）こんにちは"),  # 中文括号保留
    ]

    all_passed = True
    for original, expected in test_cases:
        result = processor.normalize_text_only(original)
        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            all_passed = False
        print(f"  {status} '{original}' -> '{result}' (expected: '{expected}')")

    return all_passed


def test_segment_merge():
    """测试片段合并"""
    print("\n=== 测试片段合并 ===")

    # 模拟 Whisper 输出的短片段
    segments = [
        {"start": 0.0, "end": 0.3, "text": "こんにちは", "log_prob": -0.5},
        {"start": 0.5, "end": 0.8, "text": "世界", "log_prob": -0.6},  # 间隔0.2s < 0.3s
        {"start": 1.2, "end": 1.8, "text": "テスト", "log_prob": -0.4},  # 间隔0.4s > 0.3s，不合并
    ]

    processor = ASRPostProcessor(PostProcessConfig(
        enable_normalize=False,
        enable_merge=True,
        enable_confidence_filter=False,
    ))

    result = processor.process(segments)

    print(f"  输入片段数: {len(segments)}")
    print(f"  输出片段数: {len(result)}")

    for i, seg in enumerate(result):
        print(f"    [{i+1}] {seg['start']:.2f}s - {seg['end']:.2f}s: {seg['text']}")

    # 验证：前两个片段应该合并
    assert len(result) == 2, f"期望2个片段，实际{len(result)}个"
    assert result[0]["text"] == "こんにちは世界", f"合并文本错误: {result[0]['text']}"
    assert abs(result[0]["end"] - 0.8) < 0.1, f"合并时间错误"

    print("  PASS 片段合并正确")
    return True


def test_confidence_filter():
    """测试置信度过滤"""
    print("\n=== 测试置信度过滤 ===")

    segments = [
        {"start": 0.0, "end": 1.0, "text": "高质量文本", "log_prob": -0.3},
        {"start": 1.0, "end": 2.0, "text": "低质量文本", "log_prob": -1.5},  # 低于阈值
        {"start": 2.0, "end": 3.0, "text": "中等质量", "log_prob": -0.8},
    ]

    processor = ASRPostProcessor(PostProcessConfig(
        enable_normalize=False,
        enable_merge=False,
        enable_confidence_filter=True,
        min_log_prob=-1.0,  # 过滤 log_prob < -1.0 的片段
    ))

    result = processor.process(segments)

    print(f"  输入片段数: {len(segments)}")
    print(f"  输出片段数: {len(result)}")

    for seg in result:
        print(f"    {seg['start']:.1f}s - {seg['end']:.1f}s: {seg['text']} (log_prob: {seg['log_prob']})")

    # 验证：只有log_prob >= -1.0的片段保留
    assert len(result) == 2, f"期望2个片段，实际{len(result)}个"
    assert all(s["log_prob"] >= -1.0 for s in result), "置信度过滤失败"

    print("  PASS 置信度过滤正确")
    return True


def test_full_pipeline():
    """测试完整后处理流程"""
    print("\n=== 测试完整后处理流程 ===")

    # 模拟 Whisper 原始输出
    raw_segments = [
        {"start": 0.0, "end": 0.4, "text": "こんにちは", "log_prob": -0.3},
        {"start": 0.6, "end": 0.9, "text": "世界！！！", "log_prob": -0.5},  # 合并 + 规范化
        {"start": 1.2, "end": 2.5, "text": "[笑い声] テスト", "log_prob": -0.8},  # 去幻觉标记
        {"start": 3.0, "end": 4.0, "text": "正常文本", "log_prob": -0.2},
    ]

    # 使用便捷函数
    result = postprocess_segments(
        raw_segments,
        normalize=True,
        merge=True,
        min_log_prob=-1.0,
    )

    print(f"  输入片段数: {len(raw_segments)}")
    print(f"  输出片段数: {len(result)}")

    for i, seg in enumerate(result):
        print(f"    [{i+1}] {seg['start']:.1f}s - {seg['end']:.1f}s: {seg['text']}")

    # 验证
    texts = [s["text"] for s in result]
    print(f"\n  规范化后的文本: {texts}")

    return True


if __name__ == "__main__":
    print("=" * 50)
    print("ASR 后处理模块测试")
    print("=" * 50)

    results = []
    results.append(("文本规范化", test_normalization()))
    results.append(("片段合并", test_segment_merge()))
    results.append(("置信度过滤", test_confidence_filter()))
    results.append(("完整流程", test_full_pipeline()))

    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + ("全部测试通过!" if all_passed else "存在失败测试"))
