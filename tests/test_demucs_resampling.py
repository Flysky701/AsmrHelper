"""The app's Demucs path resamples without a second Torch-coupled audio wheel."""
import builtins
from types import SimpleNamespace

import numpy as np
import soundfile as sf
import torch

from src.core import vocal_separator


def test_demucs_resamples_and_writes_without_torchaudio(tmp_path, monkeypatch):
    original_import = builtins.__import__

    def reject_torchaudio(name, *args, **kwargs):
        if name.startswith("torchaudio"):
            raise AssertionError("Demucs separation must not require Torchaudio")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_torchaudio)
    separator = vocal_separator.VocalSeparator.__new__(vocal_separator.VocalSeparator)
    separator.model = SimpleNamespace(samplerate=16000, audio_channels=2, sources=["vocals"])
    separator.device = "cpu"
    separator.progress = False
    source = tmp_path / "synth.wav"
    sf.write(source, .1 * np.sin(np.arange(800) * 2 * np.pi * 220 / 8000), 8000)

    def apply(model, wav, *, device):
        assert tuple(wav.shape) == (1, 2, 1600)
        assert torch.isfinite(wav).all()
        return wav[:, None]

    monkeypatch.setattr(vocal_separator, "apply_model", apply)
    paths = separator.separate(str(source), str(tmp_path / "result"))
    audio, rate = sf.read(paths["vocals"], always_2d=True)
    assert rate == 16000 and audio.shape == (1600, 2)
    assert np.isfinite(audio).all() and np.max(np.abs(audio)) > .01
