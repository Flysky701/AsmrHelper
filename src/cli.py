"""
ASMR Helper CLI 入口

用法:
    python -m src.cli --task asmr --input audio.wav
    python -m src.cli --task asr --input audio.wav
"""

import os
import sys
from pathlib import Path
from typing import Optional

import click

# 添加项目根目录到 sys.path（支持直接运行脚本）
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core import Pipeline, PipelineConfig


@click.group()
@click.version_option(version="0.2.0")
def cli():
    """ASMR Helper - ASMR 音频汉化工具"""
    pass


@cli.command()
@click.option("--input", "-i", "input_path", required=True, help="输入音频文件路径")
@click.option("--output", "-o", "output_dir", default=None, help="输出目录")
@click.option("--source-lang", default="ja", help="源语言代码 (ja/zh/en)")
@click.option("--target-lang", default="zh", help="目标语言代码")
@click.option("--tts-engine", default="edge", type=click.Choice(["edge", "qwen3"]), help="TTS 引擎")
@click.option("--tts-voice", default="zh-CN-XiaoxiaoNeural", help="TTS 音色")
@click.option("--vocal-model", default="htdemucs", help="人声分离模型")
@click.option("--asr-model", default="base", help="ASR 模型大小")
@click.option("--translate-provider", default="deepseek", help="翻译提供商")
@click.option("--tts-delay", default=0, type=float, help="TTS 延迟 (ms)")
@click.option("--skip-existing", is_flag=True, help="跳过已存在的步骤")
def asmr(
    input_path: str,
    output_dir: Optional[str],
    source_lang: str,
    target_lang: str,
    tts_engine: str,
    tts_voice: str,
    vocal_model: str,
    asr_model: str,
    translate_provider: str,
    tts_delay: float,
    skip_existing: bool,
):
    """运行 ASMR 双语双轨流程"""
    # 语言映射
    lang_map = {
        "ja": ("日文", "中文"),
        "zh": ("中文", "英文"),
        "en": ("英文", "中文"),
    }
    source, target = lang_map.get(source_lang, ("日文", "中文"))

    # 创建配置
    config = PipelineConfig(
        input_path=input_path,
        output_dir=output_dir or "",
        use_vocal_separator=True,
        vocal_model=vocal_model,
        asr_model=asr_model,
        asr_language=source_lang,
        use_translate=True,
        translate_provider=translate_provider,
        source_lang=source,
        target_lang=target,
        use_tts=True,
        tts_engine=tts_engine,
        tts_voice=tts_voice,
        use_mixer=True,
        tts_delay_ms=tts_delay,
        skip_existing=skip_existing,
    )

    # 运行流水线
    pipeline = Pipeline(config)
    results = pipeline.run(preset="asmr_bilingual")

    click.echo("\n处理完成!")
    if results.get("mix_path"):
        click.echo(f"输出文件: {results['mix_path']}")


@cli.command()
@click.option("--input", "-i", "input_path", required=True, help="输入音频文件路径")
@click.option("--output", "-o", "output_path", default=None, help="输出文本文件路径")
@click.option("--model", default="base", help="Whisper 模型大小")
@click.option("--language", default="ja", help="语言代码")
def asr_cmd(input_path: str, output_path: Optional[str], model: str, language: str):
    """仅进行 ASR 语音识别"""
    from src.core import ASRRecognizer

    click.echo(f"识别音频: {input_path}")

    recognizer = ASRRecognizer(model_size=model, language=language)
    results = recognizer.recognize(input_path, output_path)

    click.echo(f"\n识别完成，共 {len(results)} 段")
    if output_path:
        click.echo(f"结果已保存: {output_path}")


@cli.command()
@click.option("--input", "-i", "input_path", required=True, help="输入文本文件路径")
@click.option("--output", "-o", "output_path", default=None, help="输出文件路径")
@click.option("--provider", default="deepseek", help="翻译提供商")
def translate_cmd(input_path: str, output_path: Optional[str], provider: str):
    """仅进行翻译"""
    from src.core import Translator

    texts = Path(input_path).read_text(encoding="utf-8").split("\n")
    texts = [t for t in texts if t.strip()]

    click.echo(f"翻译 {len(texts)} 段文本...")

    translator = Translator(provider=provider)
    results = translator.translate_batch(texts)

    if output_path:
        Path(output_path).write_text("\n".join(results), encoding="utf-8")
        click.echo(f"翻译完成，结果已保存: {output_path}")
    else:
        for r in results:
            click.echo(r)


@cli.command()
@click.option("--input", "-i", "input_path", required=True, help="输入文本文件路径")
@click.option("--output", "-o", "output_path", required=True, help="输出音频文件路径")
@click.option("--engine", default="edge", type=click.Choice(["edge", "qwen3"]), help="TTS 引擎")
@click.option("--voice", default="zh-CN-XiaoxiaoNeural", help="TTS 音色")
def tts_cmd(input_path: str, output_path: str, engine: str, voice: str):
    """仅进行 TTS 语音合成"""
    from src.core import TTSEngine

    text = Path(input_path).read_text(encoding="utf-8")

    click.echo(f"合成语音: {input_path}")

    tts_engine = TTSEngine(engine=engine, voice=voice)
    result_path = tts_engine.synthesize(text, output_path)

    click.echo(f"合成完成: {result_path}")


@cli.command()
def presets():
    """显示可用预设"""
    from src.core import Pipeline

    click.echo("可用预设:\n")
    for name, desc in Pipeline.PRESETS.items():
        click.echo(f"  {name:20s} - {desc}")


if __name__ == "__main__":
    cli()
