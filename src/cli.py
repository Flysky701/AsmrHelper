"""
ASMR Helper CLI entrypoints.
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

import click

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.app.errors import AppError
from src.app import PipelineRequest
from src.app.services import get_asr_service
from src.app.services import get_model_service as get_app_model_service
from src.app.services import get_pipeline_service
from src.app.services import get_translation_service, get_tts_service


def _run_app_command(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except AppError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


def _emit_key_value(label: str, value: Any) -> None:
    click.echo(f"{label}: {value}")


def _emit_saved_output(path: Optional[str]) -> None:
    if path:
        _emit_key_value("Saved", path)


def _emit_status_line(name: str, status: str, detail: str) -> None:
    click.echo(f"{name}: {status} ({detail})")


def _emit_command_error(message: str) -> None:
    raise click.ClickException(message)


def _artifact_path(result: Any, name: str) -> Optional[str]:
    artifacts = getattr(result, "artifacts", None)
    if artifacts is None:
        return None
    if hasattr(artifacts, "get"):
        return artifacts.get(name)
    files = getattr(artifacts, "files", None)
    if isinstance(files, dict):
        return files.get(name)
    return None


def _primary_output(result: Any) -> Optional[str]:
    artifacts = getattr(result, "artifacts", None)
    primary_output = getattr(artifacts, "primary_output", None)
    if primary_output:
        return primary_output
    return getattr(result, "mix_path", None) or getattr(result, "exported_subtitle", None)


def _emit_pipeline_result(result: Any) -> None:
    task = getattr(result, "task", None)
    if task is not None:
        _emit_key_value("Task", f"{task.task_id} [{task.state}]")
    elif getattr(result, "task_id", None) and getattr(result, "task_state", None):
        _emit_key_value("Task", f"{result.task_id} [{result.task_state}]")

    _emit_saved_output(_primary_output(result))

    mix_path = _artifact_path(result, "mix") or getattr(result, "mix_path", None)
    subtitle_path = _artifact_path(result, "subtitle") or getattr(result, "exported_subtitle", None)
    if mix_path:
        _emit_key_value("Mix", mix_path)
    if subtitle_path:
        _emit_key_value("Subtitle", subtitle_path)
    if result.error_message:
        _emit_key_value("Warning", result.error_message)


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

    result = _run_app_command(get_pipeline_service().run_audio_pipeline, request)

    click.echo("\nPipeline completed.")
    _emit_pipeline_result(result)


@pipeline_group.command(name="presets")
def pipeline_presets():
    """Show available pipeline presets."""
    from src.core.pipeline import Pipeline

    click.echo("Available presets:\n")
    for name, desc in Pipeline.PRESETS.items():
        click.echo(f"  {name:20s} - {desc}")


@cli.command(name="asr")
@click.option("--input", "-i", "input_path", required=True, help="Input audio file path")
@click.option("--output", "-o", "output_path", default=None, help="Output text file path")
@click.option("--model", default="base", help="Whisper model size")
@click.option("--language", default="ja", help="Language code")
def asr_cmd(input_path: str, output_path: Optional[str], model: str, language: str):
    """Run standalone ASR through the application API layer."""
    click.echo(f"Recognizing audio: {input_path}")
    result = _run_app_command(
        get_asr_service().transcribe_file,
        input_path=input_path,
        output_path=output_path,
        model=model,
        language=language,
    )

    click.echo(f"\nRecognition finished, {len(result.segments)} segments")
    _emit_saved_output(result.output_path)


@cli.command(name="translate")
@click.option("--input", "-i", "input_path", required=True, help="Input text file path")
@click.option("--output", "-o", "output_path", default=None, help="Output file path")
@click.option("--provider", default="deepseek", help="Translation provider")
def translate_cmd(input_path: str, output_path: Optional[str], provider: str):
    """Run standalone translation through the application API layer."""
    result = _run_app_command(
        get_translation_service().translate_file,
        input_path=input_path,
        output_path=output_path,
        provider=provider,
    )

    click.echo(f"Translating {len(result.items)} lines...")
    if output_path:
        _emit_saved_output(output_path)
    else:
        for item in result.items:
            click.echo(item)


@cli.command(name="tts")
@click.option("--input", "-i", "input_path", required=True, help="Input text file path")
@click.option("--output", "-o", "output_path", required=True, help="Output audio file path")
@click.option("--engine", default="edge", type=click.Choice(["edge", "qwen3"]), help="TTS engine")
@click.option("--voice", default="zh-CN-XiaoxiaoNeural", help="TTS voice")
def tts_cmd(input_path: str, output_path: str, engine: str, voice: str):
    """Run standalone TTS through the application API layer."""
    click.echo(f"Synthesizing audio: {input_path}")
    result = _run_app_command(
        get_tts_service().synthesize_file,
        input_path=input_path,
        output_path=output_path,
        engine=engine,
        voice=voice,
    )

    _emit_saved_output(result.output_path)


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
    """Install a model through the application API layer."""
    service = get_app_model_service()
    result = _run_app_command(service.install_model, model_id, mirror=mirror, force=force)
    click.echo(f"Model installed: {result.model_id} [{result.status}]")


@model_group.command(name="verify")
@click.argument("model_id", required=False)
def model_verify(model_id: Optional[str]):
    """Verify model availability and configuration through the application API layer."""
    service = get_app_model_service()
    results = _run_app_command(service.verify_models, model_id=model_id)

    failed = False
    for result in results:
        _emit_status_line(result.model_id, result.status, result.detail)
        failed = failed or not result.success

    if failed:
        _emit_command_error("Some models failed verification")


@model_group.command(name="remove")
@click.argument("model_id")
def model_remove(model_id: str):
    """Remove a local model through the application API layer."""
    service = get_app_model_service()
    result = _run_app_command(service.remove_model, model_id)
    click.echo(f"Model removed: {result.model_id} [{result.status}]")


if __name__ == "__main__":
    cli()
