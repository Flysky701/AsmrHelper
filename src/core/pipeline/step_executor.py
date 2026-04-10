"""
Pipeline 执行层解耦：专注于步骤流转与调用协调，剥离大段的 if-else 与文件读写逻辑。
"""
import time
from pathlib import Path
from typing import Dict, Any, Callable, Optional
import torch

class StepExecutor:
    def __init__(self, config, path_planner, subtitle_strategy):
        self.config = config
        self.path_planner = path_planner
        self.subtitle_strategy = subtitle_strategy
        
        # Injected dependencies
        self._injected_separator = None
        self._injected_recognizer = None
        self._injected_translator = None
        self._injected_tts_engine = None
        self._injected_mixer = None
        
        # State tracking
        self.current_step = 0
        self.total_steps = 0
        self.results = {}
        self.progress_callback = None
        
    def inject(self, separator=None, recognizer=None, translator=None, tts_engine=None, mixer=None):
        self._injected_separator = separator
        self._injected_recognizer = recognizer
        self._injected_translator = translator
        self._injected_tts_engine = tts_engine
        self._injected_mixer = mixer
        
    def _report(self, msg: str):
        print(msg)
        if self.progress_callback:
            self.progress_callback(msg)

    def execute_separation(self, active_steps, subtitle_ctx, task_name, input_path, by_product_dir):
        from src.core.vocal_separator import VocalSeparator
        
        if "vocal_separator" not in active_steps:
            self.results["vocal_path"] = str(input_path)
            if subtitle_ctx.has_subtitle:
                self._report(f"[{self.current_step}/{self.total_steps}] [跳过] 人声分离 (有{subtitle_ctx.subtitle_type}字幕，直接使用原音频)")
                self.results["steps"]["vocal_separator"] = {"duration": 0, "skipped": True, "source": "original"}
            else:
                self._report(f"[{self.current_step}/{self.total_steps}] [跳过] 人声分离 (直接使用输入文件)")
        elif self.config.use_vocal_separator:
            vocal_path = by_product_dir / "vocal.wav"
            self.current_step += 1
            if self.config.skip_existing and vocal_path.exists():
                self._report(f"[{self.current_step}/{self.total_steps}] [跳过] 人声分离已存在: {vocal_path.name}")
                self.results["steps"]["vocal_separator"] = {
                    "duration": 0, "skipped": True, "source": "separated", "output": str(vocal_path)
                }
            else:
                self._report(f"\n[{self.current_step}/{self.total_steps}] 人声分离 (Demucs)...")
                t1 = time.time()
                try:
                    separator = self._injected_separator or VocalSeparator(model_name=self.config.vocal_model)
                    sep_results = separator.separate(str(input_path), str(by_product_dir), stems=["vocals"])
                    vocal_path = Path(sep_results.get("vocals", ""))
                    self.results["steps"]["vocal_separator"] = {
                        "duration": time.time() - t1, "output": str(vocal_path), "source": "separated"
                    }
                except Exception as e:
                    self._report(f"[WARN] 人声分离失败，使用原音: {e}")
                    self.results["steps"]["vocal_separator"] = {"error": str(e), "recoverable": True}
                    vocal_path = input_path
                finally:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
            self.results["vocal_path"] = str(vocal_path)
        else:
            self.results["vocal_path"] = str(input_path)
        
        return Path(self.results["vocal_path"])

    def execute_asr(self, active_steps, subtitle_ctx, vocal_path, by_product_dir):
        from src.core.asr import ASRRecognizer
        
        asr_text_path = by_product_dir / "asr_result.txt"
        timestamped_segments = []
        
        if "asr" not in active_steps or subtitle_ctx.has_subtitle:
            if subtitle_ctx.has_subtitle:
                self.current_step += 1
                self._report(f"[{self.current_step}/{self.total_steps}] [跳过] ASR (使用{subtitle_ctx.subtitle_type}字幕时间戳)")
                subtitle_entries = self.subtitle_strategy.load_entries(subtitle_ctx.subtitle_path)
                timestamped_segments = self.subtitle_strategy.to_segments(subtitle_entries)
                self.results["steps"]["asr"] = {
                    "duration": 0, "skipped": True, "source": subtitle_ctx.subtitle_type.lower(), 
                    "segments": len(timestamped_segments), "cleaned": self.config.clean_subtitle
                }
        else:
            self.current_step += 1
            if self.config.skip_existing and asr_text_path.exists():
                self._report(f"[{self.current_step}/{self.total_steps}] [提示] 检测到已有 ASR 文本，重新识别以保证时间戳完整")
            
            self._report(f"\n[{self.current_step}/{self.total_steps}] ASR 语音识别 (Whisper)...")
            t1 = time.time()
            try:
                recognizer = self._injected_recognizer or ASRRecognizer(
                    model_size=self.config.asr_model, language=self.config.asr_language
                )
                asr_results = recognizer.recognize(str(vocal_path), str(asr_text_path))
                timestamped_segments = asr_results.copy()
                self.results["steps"]["asr"] = {
                    "duration": time.time() - t1, "segments": len(asr_results), "output": str(asr_text_path)
                }
            except Exception as e:
                self._report(f"[WARN] ASR识别失败: {e}")
                self.results["steps"]["asr"] = {"error": str(e), "recoverable": True}
                timestamped_segments = []
            finally:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    
        self.results["timestamped_segments"] = timestamped_segments
        return timestamped_segments

    def execute_translate(self, active_steps, subtitle_ctx, timestamped_segments, by_product_dir):
        from src.core.translate import SubtitleTranslator
        
        translated_path = by_product_dir / "translated.txt"
        translations = []
        
        def _attach(segments, texts):
            if not segments: return
            if len(texts) != len(segments):
                self._report(f"[WARN] 翻译与时间轴不一致: translations={len(texts)}, segments={len(segments)}，将自动补齐/截断")
            normalized = list(texts[:len(segments)])
            if len(normalized) < len(segments):
                normalized.extend([""] * (len(segments) - len(normalized)))
            for seg, trans in zip(segments, normalized):
                seg["translation"] = trans

        if "translate" not in active_steps or subtitle_ctx.is_chinese_subtitle:
            if subtitle_ctx.is_chinese_subtitle:
                self.current_step += 1
                translations = subtitle_ctx.subtitle_translations
                translated_path.write_text("\n".join(translations), encoding="utf-8")
                self._report(f"[{self.current_step}/{self.total_steps}] [跳过] 翻译 ({subtitle_ctx.subtitle_type}字幕已是中文)")
                _attach(timestamped_segments, translations)
                self.results["steps"]["translate"] = {
                    "duration": 0.0, "segments": len(translations), "source": f"{subtitle_ctx.subtitle_type.lower()}_zh",
                    "skipped": True, "output": str(translated_path)
                }
        else:
            self.current_step += 1
            if self.config.skip_existing and translated_path.exists():
                self._report(f"[{self.current_step}/{self.total_steps}] [跳过] 翻译已存在: {translated_path.name}")
                translations = [line.strip() for line in translated_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                _attach(timestamped_segments, translations)
                self.results["steps"]["translate"] = {
                    "duration": 0.0, "segments": len(translations), "skipped": True, "output": str(translated_path)
                }
            else:
                self._report(f"\n[{self.current_step}/{self.total_steps}] 文本翻译...")
                t1 = time.time()
                try:
                    source_texts = [seg.get("text", "") for seg in timestamped_segments]
                    source_path = by_product_dir / "source_for_translate.txt"
                    source_path.write_text("\n".join(source_texts), encoding="utf-8")
                    
                    translator = self._injected_translator or SubtitleTranslator(
                        provider=self.config.translate_provider,
                        model=self.config.translate_model,
                        prompt_template=self.config.translate_prompt,
                        batch_size=self.config.translate_batch_size
                    )
                    translations = translator.translate_file(str(source_path), str(translated_path))
                    _attach(timestamped_segments, translations)
                    self.results["steps"]["translate"] = {
                        "duration": time.time() - t1, "segments": len(translations), "output": str(translated_path)
                    }
                except Exception as e:
                    self._report(f"[WARN] 翻译失败: {e}")
                    self.results["steps"]["translate"] = {"error": str(e), "recoverable": True}
                    
        self.results["translations"] = translations
        return translations

    def execute_tts(self, active_steps, timestamped_segments, by_product_dir):
        from src.core.tts import TTSEngine
        
        tts_audio_path = by_product_dir / "tts_output.wav"
        
        if "tts" not in active_steps:
            pass
        else:
            self.current_step += 1
            if self.config.skip_existing and tts_audio_path.exists():
                self._report(f"[{self.current_step}/{self.total_steps}] [跳过] TTS 音频已存在: {tts_audio_path.name}")
                self.results["steps"]["tts"] = {
                    "duration": 0.0, "skipped": True, "output": str(tts_audio_path),
                    "engine": self.config.tts_engine, "voice": self.config.tts_voice
                }
            else:
                self._report(f"\n[{self.current_step}/{self.total_steps}] TTS 语音合成 ({self.config.tts_engine})...")
                t1 = time.time()
                try:
                    engine = self._injected_tts_engine or TTSEngine(
                        engine_type=self.config.tts_engine,
                        voice=self.config.tts_voice,
                        speed=self.config.tts_speed,
                        voice_profile_id=self.config.voice_profile_id
                    )
                    
                    # Convert segments format for TTS
                    voice_segments = []
                    for i, seg in enumerate(timestamped_segments, 1):
                        start_time = seg.get("start", 0)
                        end_time = seg.get("end", start_time + 5.0)
                        text = seg.get("translation", seg.get("text", ""))
                        if not text: continue
                        voice_segments.append({
                            "index": f"{i:04d}",
                            "text": text,
                            "original": seg.get("text", ""),
                            "start_time": start_time,
                            "end_time": end_time
                        })
                    
                    engine.synthesize_segments(voice_segments, str(by_product_dir), str(tts_audio_path))
                    self.results["steps"]["tts"] = {
                        "duration": time.time() - t1,
                        "segments": len(voice_segments),
                        "output": str(tts_audio_path),
                        "engine": self.config.tts_engine,
                        "voice": self.config.tts_voice
                    }
                    
                    # Release Qwen3 model memory
                    if getattr(engine, "engine", None):
                        if hasattr(engine.engine, "unload"):
                            engine.engine.unload()
                except Exception as e:
                    self._report(f"[WARN] TTS合成失败: {e}")
                    import traceback; traceback.print_exc()
                    self.results["steps"]["tts"] = {"error": str(e), "recoverable": True}
                finally:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        
        self.results["tts_path"] = str(tts_audio_path)
        return tts_audio_path

    def execute_mix(self, active_steps, vocal_path, input_path, tts_audio_path, mix_path):
        from src.mixer import Mixer
        
        if "mixer" not in active_steps:
            pass
        else:
            self.current_step += 1
            self._report(f"\n[{self.current_step}/{self.total_steps}] 混合音频...")
            t1 = time.time()
            try:
                mixer = self._injected_mixer or Mixer()
                vocal_path_str = str(vocal_path) if vocal_path else str(input_path)
                
                # Check if we actual separated vocals
                source_is_separated = (
                    "vocal_separator" in self.results.get("steps", {}) 
                    and "error" not in self.results["steps"]["vocal_separator"]
                    and vocal_path_str != str(input_path)
                )
                
                if Path(tts_audio_path).exists():
                    mixer.mix_audio(
                        original_path=str(input_path),
                        vocals_path=vocal_path_str,
                        translated_path=str(tts_audio_path),
                        output_path=str(mix_path),
                        original_volume=self.config.original_volume,
                        translated_volume=self.config.tts_ratio,
                        delay_ms=self.config.tts_delay,
                        ducking=False,
                        source_is_separated=source_is_separated
                    )
                else:
                    self._report(f"[WARN] 找不到 TTS 音频 {tts_audio_path}，将复制原音频")
                    import shutil
                    shutil.copy2(str(input_path), str(mix_path))
                    
                self.results["steps"]["mixer"] = {
                    "duration": time.time() - t1, "output": str(mix_path)
                }
            except Exception as e:
                self._report(f"[WARN] 混音失败: {e}")
                self.results["steps"]["mixer"] = {"error": str(e), "recoverable": False}