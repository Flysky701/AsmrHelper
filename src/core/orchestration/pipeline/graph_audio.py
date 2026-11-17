"""Graph adapters for local, model-free audio operations."""
from __future__ import annotations

from pathlib import Path

from .graph_catalog import is_multitrack, input_ports


def local_audio_node(node):
    return is_multitrack(node) or node.get("kind") == "audio_difference"


def run_audio_node(node, inputs, directory, cancel_event=None):
    from .graph_adapters import GraphValue, _duration

    def check_cancel():
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("用户取消任务")

    check_cancel()
    for port in input_ports(node):
        value = inputs.get(port)
        if value is None or value.kind != "audio" or not value.path or not Path(value.path).is_file():
            raise ValueError(f"{port} 需要有效音频输入")
        _duration(value)
    options = node["options"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if is_multitrack(node):
        from src.mixer.multitrack import mix_tracks
        result = mix_tracks([
            {**track, "path": inputs[track["id"]].path} for track in options["tracks"]
        ], str(directory / "mix.wav"), output_length=options.get("output_length", "longest"),
            check_cancel=check_cancel)
        # Independent sources establish a new timeline; do not inherit a source's
        # pairing assertion after assembling unrelated clips and offsets.
        metadata = {"timeline_id": f"mix:{directory.resolve()}", "pair_confirmed": True,
                    "output_length": options.get("output_length", "longest"),
                    "tracks": [{key: value for key, value in track.items()}
                               for track in options["tracks"]]}
    else:
        from src.mixer.difference import extract_difference
        result = extract_difference(
            inputs["mixed"].path, inputs["reference"].path, str(directory / "difference.wav"),
            calibration_start=options.get("calibration_start", 0),
            calibration_end=options.get("calibration_end"), offset_ms=options.get("offset_ms", 0),
            gain_left=options.get("gain_left", 1), gain_right=options.get("gain_right", 1),
            auto_align=options.get("alignment", "manual") == "auto",
            auto_gain=options.get("match_gain", False),
            search_seconds=options.get("max_shift_seconds", 5), check_cancel=check_cancel,
        )
        metadata = dict(inputs["mixed"].metadata)
    metadata.update({key: value for key, value in result.items() if key != "path"})
    check_cancel()
    value = GraphValue("audio", result["path"], metadata=metadata)
    _duration(value)
    return {"audio": value}
