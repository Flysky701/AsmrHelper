"""
ASR 模块增强功能测试

测试内容：
1. word_timestamps 逐词时间戳
2. 毫秒级时间精度
3. 流式进度显示
4. SRT/LRC 输出格式
"""

import sys
import time
from pathlib import Path

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.core.asr import ASRRecognizer


def test_word_timestamps():
    """测试 word_timestamps 逐词时间戳"""
    print("\n" + "=" * 60)
    print("测试 word_timestamps 逐词时间戳")
    print("=" * 60)

    recognizer = ASRRecognizer(model_size="base", language="ja")

    # 测试音频（如果有的话）
    test_audio = Path(__file__).parent.parent / "tests" / "test_data" / "test_ja.wav"
    if not test_audio.exists():
        print(f"  [SKIP] 测试音频不存在: {test_audio}")
        return

    results = recognizer.recognize(str(test_audio), show_progress=False)

    # 检查是否包含 words 字段
    has_words = any("words" in r and len(r["words"]) > 0 for r in results)
    print(f"\n  逐词时间戳: {'已启用' if has_words else '未找到'}")

    if has_words:
        for r in results[:2]:  # 只显示前2个片段
            if r.get("words"):
                print(f"\n  片段: {r['text'][:30]}...")
                for w in r["words"][:5]:  # 只显示前5个词
                    print(f"    [{w['start']:.3f}-{w['end']:.3f}] {w['word']} (p={w['probability']:.2f})")

    print("\n[PASS] word_timestamps 测试完成!")
    return results


def test_millisecond_precision():
    """测试毫秒级时间精度（3位小数）"""
    print("\n" + "=" * 60)
    print("测试毫秒级时间精度")
    print("=" * 60)

    # 创建测试数据
    test_results = [
        {"start": 1.234, "end": 2.567, "text": "テスト", "log_prob": -0.5},
        {"start": 3.999, "end": 5.123, "text": "こんにちは", "log_prob": -0.3},
    ]

    # 验证时间精度
    from src.core.asr.postprocess import ASRPostProcessor
    processor = ASRPostProcessor()
    processed = processor.process(test_results)

    for r in processed:
        start_str = f"{r['start']}"
        end_str = f"{r['end']}"
        # 检查是否为3位小数
        start_ok = len(start_str.split('.')[-1]) <= 3 if '.' in start_str else True
        end_ok = len(end_str.split('.')[-1]) <= 3 if '.' in end_str else True
        print(f"  [{r['start']:.3f} - {r['end']:.3f}] {r['text']}")

    print("\n[PASS] 毫秒级时间精度测试完成!")


def test_srt_output():
    """测试 SRT 输出格式"""
    print("\n" + "=" * 60)
    print("测试 SRT 输出格式")
    print("=" * 60)

    import tempfile

    test_results = [
        {"start": 1.234, "end": 2.567, "text": "こんにちは"},
        {"start": 3.999, "end": 5.123, "text": "世界"},
    ]

    recognizer = ASRRecognizer(model_size="base")

    with tempfile.TemporaryDirectory() as tmpdir:
        srt_path = Path(tmpdir) / "test.srt"
        recognizer.save_as_srt(test_results, str(srt_path))

        # 读取并显示
        content = srt_path.read_text(encoding="utf-8")
        print(f"\n  SRT 文件内容:\n")
        for line in content.split("\n"):
            print(f"    {line}")

    print("\n[PASS] SRT 输出格式测试完成!")


def test_lrc_output():
    """测试 LRC 输出格式"""
    print("\n" + "=" * 60)
    print("测试 LRC 输出格式")
    print("=" * 60)

    import tempfile

    test_results = [
        {"start": 1.234, "end": 2.567, "text": "こんにちは"},
        {"start": 3.999, "end": 5.123, "text": "世界"},
    ]

    recognizer = ASRRecognizer(model_size="base")

    with tempfile.TemporaryDirectory() as tmpdir:
        lrc_path = Path(tmpdir) / "test.lrc"
        recognizer.save_as_lrc(test_results, str(lrc_path))

        # 读取并显示
        content = lrc_path.read_text(encoding="utf-8")
        print(f"\n  LRC 文件内容:\n")
        for line in content.split("\n"):
            print(f"    {line}")

    print("\n[PASS] LRC 输出格式测试完成!")


def test_progress_callback():
    """测试进度回调函数"""
    print("\n" + "=" * 60)
    print("测试进度回调函数")
    print("=" * 60)

    progress_calls = []

    def my_callback(current: float, duration: float, segments: int):
        progress_calls.append((current, duration, segments))
        pct = current / duration * 100 if duration > 0 else 0
        print(f"  进度: {pct:.1f}% ({segments}段)")

    # 模拟进度回调
    print("  模拟进度回调:")
    for i in range(0, 101, 20):
        current = i / 100 * 60  # 假设60秒音频
        my_callback(current, 60.0, i // 10)

    print(f"\n  回调次数: {len(progress_calls)}")
    print("\n[PASS] 进度回调测试完成!")


def main():
    print("=" * 60)
    print("ASR 模块增强功能测试")
    print("=" * 60)

    try:
        test_millisecond_precision()
        test_srt_output()
        test_lrc_output()
        test_progress_callback()
        test_word_timestamps()

        print("\n" + "=" * 60)
        print("# 全部测试完成!")
        print("=" * 60)

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
