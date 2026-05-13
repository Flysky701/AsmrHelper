"""
ASMR Helper CLI entrypoints.
"""

import sys
from pathlib import Path
from typing import Optional

import click

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core import Pipeline, PipelineConfig
from src.core.resources import get_model_service


@click.group()
@click.version_option(version="0.2.0")
def cli():
    """ASMR Helper CLI."""
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
    """运行 ASMR 双语双轨流程。"""
    lang_map = {
        "ja": ("日文", "中文"),
        "zh": ("中文", "英文"),
        "en": ("英文", "中文"),
    }
    source, target = lang_map.get(source_lang, ("日文", "中文"))

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

    pipeline = Pipeline(config)
    results = pipeline.run(preset="asmr_bilingual")

    click.echo("\n处理完成!")
    if results.get("mix_path"):
        click.echo(f"输出文件: {results['mix_path']}")


@cli.command(name="asr")
@click.option("--input", "-i", "input_path", required=True, help="输入音频文件路径")
@click.option("--output", "-o", "output_path", default=None, help="输出文本文件路径")
@click.option("--model", default="base", help="Whisper 模型大小")
@click.option("--language", default="ja", help="语言代码")
def asr_cmd(input_path: str, output_path: Optional[str], model: str, language: str):
    """仅进行 ASR 语音识别。"""
    from src.core import ASRRecognizer

    click.echo(f"识别音频: {input_path}")
    recognizer = ASRRecognizer(model_size=model, language=language)
    results = recognizer.recognize(input_path, output_path)

    click.echo(f"\n识别完成，共 {len(results)} 段")
    if output_path:
        click.echo(f"结果已保存: {output_path}")


@cli.command(name="translate")
@click.option("--input", "-i", "input_path", required=True, help="输入文本文件路径")
@click.option("--output", "-o", "output_path", default=None, help="输出文件路径")
@click.option("--provider", default="deepseek", help="翻译提供商")
def translate_cmd(input_path: str, output_path: Optional[str], provider: str):
    """仅进行翻译。"""
    from src.core import Translator

    texts = Path(input_path).read_text(encoding="utf-8").split("\n")
    texts = [text for text in texts if text.strip()]

    click.echo(f"翻译 {len(texts)} 段文本...")
    translator = Translator(provider=provider)
    results = translator.translate_batch(texts)

    if output_path:
        Path(output_path).write_text("\n".join(results), encoding="utf-8")
        click.echo(f"翻译完成，结果已保存: {output_path}")
    else:
        for result in results:
            click.echo(result)


@cli.command(name="tts")
@click.option("--input", "-i", "input_path", required=True, help="输入文本文件路径")
@click.option("--output", "-o", "output_path", required=True, help="输出音频文件路径")
@click.option("--engine", default="edge", type=click.Choice(["edge", "qwen3"]), help="TTS 引擎")
@click.option("--voice", default="zh-CN-XiaoxiaoNeural", help="TTS 音色")
def tts_cmd(input_path: str, output_path: str, engine: str, voice: str):
    """仅进行 TTS 语音合成。"""
    from src.core import TTSEngine

    text = Path(input_path).read_text(encoding="utf-8")
    click.echo(f"合成语音: {input_path}")

    tts_engine = TTSEngine(engine=engine, voice=voice)
    result_path = tts_engine.synthesize(text, output_path)
    click.echo(f"合成完成: {result_path}")


@cli.command()
def presets():
    """显示可用预设。"""
    click.echo("可用预设:\n")
    for name, desc in Pipeline.PRESETS.items():
        click.echo(f"  {name:20s} - {desc}")


@cli.group(name="model")
def model_group():
    """模型管理。"""
    pass


@model_group.command(name="list")
@click.option("--kind", type=click.Choice(["local", "cloud"]), default=None, help="模型类型过滤")
@click.option("--category", type=click.Choice(["asr", "tts", "separator", "llm"]), default=None, help="模型分类过滤")
def model_list(kind: Optional[str], category: Optional[str]):
    """列出已注册模型。"""
    service = get_model_service()
    entries = service.list_models(kind=kind, category=category)
    for entry in entries:
        backend = entry.provider or entry.engine or "-"
        click.echo(f"{entry.id:24s} {entry.kind:6s} {entry.category:10s} {backend:16s} {entry.display_name}")


@model_group.command(name="status")
@click.argument("model_id", required=False)
@click.option("--kind", type=click.Choice(["local", "cloud"]), default=None, help="模型类型过滤")
@click.option("--category", type=click.Choice(["asr", "tts", "separator", "llm"]), default=None, help="模型分类过滤")
def model_status(model_id: Optional[str], kind: Optional[str], category: Optional[str]):
    """查看模型状态。"""
    service = get_model_service()
    if model_id:
        status = service.get_status(model_id)
        click.echo(f"{status.model_id}: {status.status} ({status.detail})")
        return

    for status in service.get_all_statuses(kind=kind, category=category):
        click.echo(f"{status.model_id:24s} {status.status:12s} {status.detail}")


@model_group.command(name="install")
@click.argument("model_id")
@click.option("--mirror", default=None, help="HuggingFace 镜像地址")
@click.option("--force", is_flag=True, help="强制重新下载")
def model_install(model_id: str, mirror: Optional[str], force: bool):
    """安装本地模型。"""
    service = get_model_service()
    try:
        success = service.install(model_id, mirror=mirror, force=force)
    except ValueError as exc:
        raise click.ClickException(str(exc))

    if not success:
        raise click.ClickException(f"模型安装失败: {model_id}")
    click.echo(f"模型安装完成: {model_id}")


@model_group.command(name="verify")
@click.argument("model_id", required=False)
def model_verify(model_id: Optional[str]):
    """校验本地模型。"""
    service = get_model_service()
    results = service.verify(model_id=model_id)
    failed = False
    for current_id, ok in results.items():
        click.echo(f"{current_id}: {'installed' if ok else 'invalid'}")
        failed = failed or not ok

    if failed:
        raise click.ClickException("部分模型校验失败")


@model_group.command(name="remove")
@click.argument("model_id")
def model_remove(model_id: str):
    """删除本地模型文件。"""
    service = get_model_service()
    try:
        service.remove(model_id)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"模型已删除: {model_id}")


if __name__ == "__main__":
    cli()
