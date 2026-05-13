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

from src.app import PipelineRequest
from src.app.services import get_model_service as get_app_model_service
from src.app.services import get_pipeline_service
from src.core import ASRRecognizer, Pipeline, TTSEngine, Translator
from src.core.resources import get_model_service as get_core_model_service


@click.group()
@click.version_option(version="0.2.0")
def cli():
    """ASMR Helper CLI."""
    pass


@cli.group(name="pipeline")
def pipeline_group():
    """Pipeline commands backed by the application API layer."""
    pass


@pipeline_group.command(name="run")
@click.option("--input", "-i", "input_path", required=True, help="Input audio file path")
@click.option("--output", "-o", "output_dir", default=None, help="Output directory")
@click.option("--source-lang", default="ja", help="Source language code (ja/zh/en)")
@click.option("--target-lang", default="zh", help="Target language code")
@click.option("--tts-engine", default="edge", type=click.Choice(["edge", "qwen3"]), help="TTS engine")
@click.option("--tts-voice", default="zh-CN-XiaoxiaoNeural", help="TTS voice")
@click.option("--vocal-model", default="htdemucs", help="Separator model")
@click.option("--asr-model", default="base", help="ASR model size")
@click.option("--translate-provider", default="deepseek", help="Translation provider")
@click.option("--tts-delay", default=0, type=float, help="TTS delay (ms)")
@click.option("--skip-existing", is_flag=True, help="Skip steps whose outputs already exist")
def pipeline_run(
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
    """Run the bilingual ASMR pipeline through the application service layer."""
    request = PipelineRequest(
        input_path=input_path,
        output_dir=output_dir or "",
        source_lang=source_lang,
        target_lang=target_lang,
        tts_engine=tts_engine,
        tts_voice=tts_voice,
        vocal_model=vocal_model,
        asr_model=asr_model,
        translate_provider=translate_provider,
        tts_delay=tts_delay,
        skip_existing=skip_existing,
    )

    try:
        result = get_pipeline_service().run_audio_pipeline(request)
    except Exception as exc:
        raise click.ClickException(str(exc))

    click.echo("\nPipeline completed.")
    if result.mix_path:
        click.echo(f"Mix: {result.mix_path}")
    if result.exported_subtitle:
        click.echo(f"Subtitle: {result.exported_subtitle}")
    if result.error_message:
        click.echo(f"Warning: {result.error_message}")


@pipeline_group.command(name="presets")
def pipeline_presets():
    """Show available pipeline presets."""
    click.echo("Available presets:\n")
    for name, desc in Pipeline.PRESETS.items():
        click.echo(f"  {name:20s} - {desc}")


@cli.command(name="asr")
@click.option("--input", "-i", "input_path", required=True, help="Input audio file path")
@click.option("--output", "-o", "output_path", default=None, help="Output text file path")
@click.option("--model", default="base", help="Whisper model size")
@click.option("--language", default="ja", help="Language code")
def asr_cmd(input_path: str, output_path: Optional[str], model: str, language: str):
    """Legacy direct ASR command."""
    click.echo(f"Recognizing audio: {input_path}")
    recognizer = ASRRecognizer(model_size=model, language=language)
    results = recognizer.recognize(input_path, output_path)

    click.echo(f"\nRecognition finished, {len(results)} segments")
    if output_path:
        click.echo(f"Saved: {output_path}")


@cli.command(name="translate")
@click.option("--input", "-i", "input_path", required=True, help="Input text file path")
@click.option("--output", "-o", "output_path", default=None, help="Output file path")
@click.option("--provider", default="deepseek", help="Translation provider")
def translate_cmd(input_path: str, output_path: Optional[str], provider: str):
    """Legacy direct translation command."""
    texts = Path(input_path).read_text(encoding="utf-8").split("\n")
    texts = [text for text in texts if text.strip()]

    click.echo(f"Translating {len(texts)} lines...")
    translator = Translator(provider=provider)
    results = translator.translate_batch(texts)

    if output_path:
        Path(output_path).write_text("\n".join(results), encoding="utf-8")
        click.echo(f"Saved: {output_path}")
    else:
        for result in results:
            click.echo(result)


@cli.command(name="tts")
@click.option("--input", "-i", "input_path", required=True, help="Input text file path")
@click.option("--output", "-o", "output_path", required=True, help="Output audio file path")
@click.option("--engine", default="edge", type=click.Choice(["edge", "qwen3"]), help="TTS engine")
@click.option("--voice", default="zh-CN-XiaoxiaoNeural", help="TTS voice")
def tts_cmd(input_path: str, output_path: str, engine: str, voice: str):
    """Legacy direct TTS command."""
    text = Path(input_path).read_text(encoding="utf-8")
    click.echo(f"Synthesizing audio: {input_path}")

    tts_engine = TTSEngine(engine=engine, voice=voice)
    result_path = tts_engine.synthesize(text, output_path)
    click.echo(f"Saved: {result_path}")


@cli.group(name="model")
def model_group():
    """Model commands."""
    pass


@model_group.command(name="list")
@click.option("--kind", type=click.Choice(["local", "cloud"]), default=None, help="Model kind filter")
@click.option("--category", type=click.Choice(["asr", "tts", "separator", "llm"]), default=None, help="Model category filter")
def model_list(kind: Optional[str], category: Optional[str]):
    """List registered models through the application API layer."""
    service = get_app_model_service()
    entries = service.list_models(kind=kind, category=category)
    for entry in entries:
        click.echo(
            f"{entry.model_id:24s} {entry.kind:6s} {entry.category:10s} "
            f"{entry.backend:16s} {entry.display_name}"
        )


@model_group.command(name="status")
@click.argument("model_id", required=False)
@click.option("--kind", type=click.Choice(["local", "cloud"]), default=None, help="Model kind filter")
@click.option("--category", type=click.Choice(["asr", "tts", "separator", "llm"]), default=None, help="Model category filter")
def model_status(model_id: Optional[str], kind: Optional[str], category: Optional[str]):
    """Show model status through the application API layer."""
    service = get_app_model_service()
    if model_id:
        status = service.get_model_status(model_id)
        click.echo(f"{status.model_id}: {status.status} ({status.detail})")
        return

    for status in service.list_model_statuses(kind=kind, category=category):
        click.echo(f"{status.model_id:24s} {status.status:12s} {status.detail}")


@model_group.command(name="install")
@click.argument("model_id")
@click.option("--mirror", default=None, help="HuggingFace mirror")
@click.option("--force", is_flag=True, help="Force redownload")
def model_install(model_id: str, mirror: Optional[str], force: bool):
    """Legacy direct model installation command."""
    service = get_core_model_service()
    try:
        success = service.install(model_id, mirror=mirror, force=force)
    except ValueError as exc:
        raise click.ClickException(str(exc))

    if not success:
        raise click.ClickException(f"Model installation failed: {model_id}")
    click.echo(f"Model installed: {model_id}")


@model_group.command(name="verify")
@click.argument("model_id", required=False)
def model_verify(model_id: Optional[str]):
    """Legacy direct model verification command."""
    service = get_core_model_service()
    results = service.verify(model_id=model_id)
    failed = False
    for current_id, ok in results.items():
        click.echo(f"{current_id}: {'installed' if ok else 'invalid'}")
        failed = failed or not ok

    if failed:
        raise click.ClickException("Some models failed verification")


@model_group.command(name="remove")
@click.argument("model_id")
def model_remove(model_id: str):
    """Legacy direct model removal command."""
    service = get_core_model_service()
    try:
        service.remove(model_id)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Model removed: {model_id}")


if __name__ == "__main__":
    cli()
