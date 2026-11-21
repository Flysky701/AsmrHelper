"""Entry point executed with the selected upstream model's Python interpreter."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace


def managed_weights(model):
    root = os.environ.get("ASMR_HELPER_MODEL_ROOT")
    directory = Path(root).resolve() / model if root else None
    return directory if directory and directory.is_dir() else None


def load_seed_vc():
    import torch
    import inference

    inference.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    inference.fp16 = inference.device.type == "cuda"
    defaults = {
        "checkpoint": os.environ.get("ASMR_SEED_VC_CHECKPOINT") or None,
        "config": os.environ.get("ASMR_SEED_VC_CONFIG") or None,
        "f0_condition": False,
        "auto_f0_adjust": False,
        "semi_tone_shift": 0,
        "length_adjust": 1.0,
        "inference_cfg_rate": 0.7,
        "fp16": inference.fp16,
    }
    managed = managed_weights("seed_vc")
    if managed and not defaults["checkpoint"] and not defaults["config"]:
        defaults["checkpoint"] = str(managed / "DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth")
        import tempfile
        import yaml
        config = yaml.safe_load((managed / "config_dit_mel_seed_uvit_whisper_small_wavenet.yml").read_text(encoding="utf-8"))
        config["model_params"]["vocoder"]["name"] = str(managed / "bigvgan")
        config["model_params"]["speech_tokenizer"]["name"] = str(managed / "whisper")
        upstream_load = inference.load_custom_model_from_hf
        def load_cached(repo_id, model_filename, config_filename=None):
            if repo_id == "funasr/campplus" and model_filename == "campplus_cn_common.bin":
                return str(managed / "campplus" / model_filename)
            return upstream_load(repo_id, model_filename, config_filename)
        inference.load_custom_model_from_hf = load_cached
        with tempfile.TemporaryDirectory() as workdir:
            config_file = Path(workdir) / "seed.yml"
            config_file.write_text(yaml.safe_dump(config), encoding="utf-8")
            model = inference.load_models(SimpleNamespace(**{**defaults, "config": str(config_file)}))
    else:
        model = inference.load_models(SimpleNamespace(**defaults))
    # Upstream's CLI entry point unconditionally loads weights. Reuse the
    # same model tuple for this batch inside the dedicated subprocess.
    inference.load_models = lambda _args: model

    def render(item):
        output = Path(item["output"])
        directory = output.with_suffix("")
        args = SimpleNamespace(
            **defaults, source=item["source"], target=item["reference"],
            output=str(directory), diffusion_steps=item["diffusion_steps"],
        )
        inference.main(args)
        files = list(directory.glob("*.wav"))
        if len(files) != 1:
            raise RuntimeError("Seed-VC did not produce one WAV file")
        files[0].replace(output)

    return render


def load_cosyvoice2():
    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel
    from cosyvoice.utils.common import set_all_random_seed

    model = AutoModel(
        model_dir=os.environ.get("ASMR_COSYVOICE2_MODEL") or str(managed_weights("cosyvoice2") or "pretrained_models/CosyVoice2-0.5B"),
    )

    def render(item):
        if item["seed"] >= 0:
            set_all_random_seed(item["seed"])
        if item["reference_text"]:
            chunks = model.inference_zero_shot(
                item["text"], item["reference_text"], item["reference"], stream=False,
            )
        else:
            chunks = model.inference_cross_lingual(item["text"], item["reference"], stream=False)
        audio = torch.cat([chunk["tts_speech"].cpu() for chunk in chunks], dim=-1)
        torchaudio.save(item["output"], audio, model.sample_rate)

    return render


def load_gpt_sovits():
    sys.path.insert(0, str(Path.cwd() / "GPT_SoVITS"))
    import soundfile as sf

    config = os.environ.get("ASMR_GPT_SOVITS_CONFIG")
    managed = managed_weights("gpt_sovits")
    if not config and managed:
        import torch
        from text.g2pw import onnx_api

        os.environ.setdefault("bert_path", str(managed / "chinese-roberta-wwm-ext-large"))
        # The Chinese frontend passes a fixed checkout-relative directory.
        # Resolve its verified Drive copy before importing the text frontend.
        original_resolve = onnx_api.download_and_decompress
        def resolve_pronunciation_model(model_dir):
            if Path(model_dir) == Path("GPT_SoVITS/text/G2PWModel"):
                return str(managed / "G2PWModel")
            return original_resolve(model_dir)
        onnx_api.download_and_decompress = resolve_pronunciation_model
        cuda = torch.cuda.is_available()
        config = {"custom": {
            "version": "v2", "device": "cuda" if cuda else "cpu", "is_half": cuda,
            "bert_base_path": str(managed / "chinese-roberta-wwm-ext-large"),
            "cnhuhbert_base_path": str(managed / "chinese-hubert-base"),
            "t2s_weights_path": str(managed / "gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt"),
            "vits_weights_path": str(managed / "gsv-v2final-pretrained/s2G2333k.pth"),
        }}
    config = config or "GPT_SoVITS/configs/tts_infer.yaml"
    from TTS_infer_pack.TTS import TTS, TTS_Config
    model = TTS(TTS_Config(config))

    def render(item):
        data = {
            "text": item["text"], "text_lang": item["language"],
            "ref_audio_path": item["reference"], "prompt_text": item["reference_text"],
            "prompt_lang": item["reference_language"],
            "text_split_method": "cut5", "streaming_mode": False,
            "return_fragment": False, "seed": item["seed"], "temperature": item["temperature"],
        }
        generator = model.run(data)
        try:
            sample_rate, audio = next(generator)
        finally:
            generator.close()
        sf.write(item["output"], audio, sample_rate)

    return render


def main():
    provider_id, request_file, result_file = sys.argv[1:]
    sys.path.insert(0, str(Path.cwd()))
    if provider_id == "cosyvoice2":
        sys.path.insert(1, str(Path.cwd() / "third_party" / "Matcha-TTS"))
    loaders = {
        "seed_vc": load_seed_vc,
        "cosyvoice2": load_cosyvoice2,
        "gpt_sovits": load_gpt_sovits,
    }
    items = json.loads(Path(request_file).read_text(encoding="utf-8"))["items"]
    render = loaders[provider_id]()
    errors = {}
    for item in items:
        try:
            render(item)
        except Exception as exc:
            errors[item["output"]] = f"{type(exc).__name__}: {exc}"
    Path(result_file).write_text(json.dumps(errors, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
