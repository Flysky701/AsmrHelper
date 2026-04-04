"""
音色工坊服务层

功能：
1. VoiceDesigner - 自然语言音色定制 + 原音频克隆
2. 封装 VoiceDesign + Base 模型的工作流
3. 支持进度回调和试音
"""

import os
import torch
import numpy as np
import soundfile as sf
from pathlib import Path
from typing import Optional, Callable, List

from src.config import PROJECT_ROOT  # 统一使用项目根目录

# 默认参考文本（用于生成参考音频）
DEFAULT_REF_TEXT = "你好，今天辛苦了，让我来帮你放松一下吧。"

# 预设音色描述模板
VOICE_TEMPLATES = {
    "治愈大姐姐": "温柔成熟的大姐姐声线，音调偏低，语速舒缓，让人感到安心和放松",
    "娇小萝莉": "可爱甜美的萝莉音，音调偏高，语速轻快，充满活力",
    "冷艳女王": "高冷优雅的女王音，音调平稳，语气冷淡，有距离感",
    "邻家女孩": "亲切自然的邻家女孩声线，音调适中，语速平常，如同好友聊天",
    "磁性低音": "低沉磁性的男性声线，音调偏低，嗓音沙哑，充满魅力",
}


class VoiceDesigner:
    """
    音色设计服务 - 封装 VoiceDesign + Base 的工作流

    使用方式：
        designer = VoiceDesigner()
        profile = designer.design_and_generate(
            description="温柔成熟的大姐姐声线",
            name="我的音色",
            progress_callback=lambda msg, pct: print(f"{pct}%: {msg}")
        )
    """

    def __init__(self, output_dir: str = None):
        """
        初始化音色设计师

        Args:
            output_dir: 输出目录，默认使用 models/voice_profiles/
        """
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            # 统一使用 PROJECT_ROOT
            self.output_dir = PROJECT_ROOT / "models" / "voice_profiles"

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _report_progress(self, callback: Optional[Callable], msg: str, percent: int):
        """报告进度"""
        if callback:
            callback(msg, percent)
        print(f"[VoiceDesigner] {percent}%: {msg}")

    def design_and_generate(
        self,
        description: str,
        name: str,
        ref_text: str = DEFAULT_REF_TEXT,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ):
        """
        从自然语言描述生成完整音色配置

        流程:
        1. 加载 VoiceDesign 模型 → 生成参考音频
        2. 卸载 VoiceDesign → 加载 Base 模型
        3. Base 模型创建 voice_clone_prompt
        4. 保存音色配置到 voice_profiles.json
        5. 返回 VoiceProfile (可直接用于 TTS)

        Args:
            description: 自然语言描述
            name: 音色名称
            ref_text: 参考音频对应的文本
            progress_callback: 进度回调 (msg, progress_percent)

        Returns:
            VoiceProfile 实例
        """
        from src.core.tts.qwen3_manager import Qwen3ModelManager
        from src.core.tts.voice_profile import VoiceProfile, get_voice_manager

        manager = get_voice_manager()

        # 生成唯一 ID (B 系列 = custom)
        custom_ids = [int(p.id[1:]) for p in manager.get_all()
                     if p.category == "custom"]
        new_id = f"B{max(custom_ids) + 1 if custom_ids else 1}"

        # 文件路径
        ref_audio = self.output_dir / f"{new_id}_ref.wav"
        prompt_cache = self.output_dir / f"{new_id}_prompt.pt"

        try:
            # ===== Step 1: 加载 VoiceDesign 模型 =====
            self._report_progress(progress_callback, "加载 VoiceDesign 模型...", 5)

            vd_model = Qwen3ModelManager.get_voice_design_model()

            # ===== Step 2: 生成参考音频 =====
            self._report_progress(progress_callback, f"生成参考音频 (描述: {description[:30]}...)", 10)

            # VoiceDesign API
            audios, sample_rate = vd_model.generate_voice_design(
                text=ref_text,
                instruct=description,
                language="chinese",
            )

            # 保存参考音频
            self._report_progress(progress_callback, "保存参考音频...", 50)
            sf.write(str(ref_audio), audios[0], sample_rate)
            print(f"[VoiceDesigner] 参考音频已保存: {ref_audio}")

            # ===== Step 3: 卸载 VoiceDesign，释放显存 =====
            self._report_progress(progress_callback, "切换到 Base 模型...", 55)
            Qwen3ModelManager.unload("voice_design")

            # ===== Step 4: 加载 Base 模型 =====
            self._report_progress(progress_callback, "加载 Base 模型...", 60)

            base_model = Qwen3ModelManager.get_base_model()

            # ===== Step 5: 创建 voice_clone_prompt =====
            self._report_progress(progress_callback, "创建音色克隆 prompt...", 70)

            # Base 模型创建 clone prompt
            voice_clone_prompt = base_model.create_voice_clone_prompt(
                ref_audio=str(ref_audio),
                ref_text=ref_text,
            )

            # 保存 prompt
            torch.save(voice_clone_prompt, str(prompt_cache))
            print(f"[VoiceDesigner] Prompt 已保存: {prompt_cache}")

            # ===== Step 6: 注册音色到管理器 =====
            self._report_progress(progress_callback, "保存音色配置...", 90)

            profile = VoiceProfile(
                id=new_id,
                name=name,
                category="custom",
                engine="qwen3_clone",
                description=description,
                design_instruct=description,
                ref_audio=str(ref_audio),
                prompt_cache=str(prompt_cache),
                generated=True,
            )

            # 添加到管理器
            manager.add_profile(profile)

            self._report_progress(progress_callback, "音色设计完成!", 100)
            print(f"[VoiceDesigner] 自定义音色 '{name}' ({new_id}) 创建成功!")
            return profile

        except Exception as e:
            print(f"[VoiceDesigner] 音色设计失败: {e}")
            import traceback
            traceback.print_exc()
            raise

    def clone_from_audio(
        self,
        audio_path: str,
        name: str,
        ref_text: str = DEFAULT_REF_TEXT,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ):
        """
        从音频文件克隆音色

        流程:
        1. 读取音频文件
        2. 加载 Base 模型
        3. 创建 voice_clone_prompt
        4. 保存音色配置到 voice_profiles.json

        Args:
            audio_path: 参考音频路径
            name: 音色名称
            ref_text: 参考音频对应的文本
            progress_callback: 进度回调 (msg, progress_percent)

        Returns:
            VoiceProfile 实例
        """
        from src.core.tts.qwen3_manager import Qwen3ModelManager
        from src.core.tts.voice_profile import VoiceProfile, get_voice_manager

        manager = get_voice_manager()

        # 验证音频文件
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"参考音频不存在: {audio_path}")

        # 生成唯一 ID (C 系列 = clone)
        clone_ids = [int(p.id[1:]) for p in manager.get_all()
                    if p.category == "clone"]
        new_id = f"C{max(clone_ids) + 1 if clone_ids else 1}"

        # 文件路径
        prompt_cache = self.output_dir / f"{new_id}_prompt.pt"

        try:
            # ===== Step 1: 加载 Base 模型 =====
            self._report_progress(progress_callback, "加载 Base 模型...", 10)
            base_model = Qwen3ModelManager.get_base_model()

            # ===== Step 2: 创建 voice_clone_prompt =====
            self._report_progress(progress_callback, f"分析音频: {audio_path.name}", 30)

            voice_clone_prompt = base_model.create_voice_clone_prompt(
                ref_audio=str(audio_path),
                ref_text=ref_text,
            )

            # 保存 prompt
            self._report_progress(progress_callback, "保存音色配置...", 80)
            torch.save(voice_clone_prompt, str(prompt_cache))
            print(f"[VoiceDesigner] Clone Prompt 已保存: {prompt_cache}")

            # ===== Step 3: 注册音色到管理器 =====
            profile = VoiceProfile(
                id=new_id,
                name=name,
                category="clone",
                engine="qwen3_clone",
                description=f"克隆自: {audio_path.name}",
                ref_audio=str(audio_path),
                prompt_cache=str(prompt_cache),
                generated=True,
            )

            manager.add_profile(profile)

            self._report_progress(progress_callback, "音色克隆完成!", 100)

            print(f"[VoiceDesigner] 克隆音色 '{name}' ({new_id}) 创建成功!")
            return profile

        except Exception as e:
            print(f"[VoiceDesigner] 音色克隆失败: {e}")
            import traceback
            traceback.print_exc()
            raise

    def preview_profile(
        self,
        profile,
        text: str = DEFAULT_REF_TEXT,
        output_path: str = None,
        speed: float = 1.0,
    ) -> str:
        """
        试听音色效果

        Args:
            profile: VoiceProfile 实例
            text: 试听文本
            output_path: 输出文件路径 (可选，默认临时文件)
            speed: 语速 (默认 1.0)

        Returns:
            生成的音频文件路径
        """
        from src.core.tts import Qwen3TTSEngine

        if output_path is None:
            output_path = self.output_dir / f"preview_{profile.id}.wav"

        try:
            # 统一使用 Qwen3TTSEngine 合成音频
            engine = Qwen3TTSEngine(voice_profile_id=profile.id, speed=speed)
            audio_path = engine.synthesize(text, str(output_path))

            return audio_path

        except Exception as e:
            print(f"[VoiceDesigner] 试音失败: {e}")
            raise

    def clone_and_preview(
        self,
        audio_path: str,
        text: str = DEFAULT_REF_TEXT,
        output_path: str = None,
        ref_text: str = DEFAULT_REF_TEXT,
    ) -> str:
        """
        直接从音频文件克隆音色并生成试音音频（不保存音色配置）

        Args:
            audio_path: 参考音频路径
            text: 待合成文本
            output_path: 输出文件路径
            ref_text: 参考音频对应的文本

        Returns:
            生成的音频文件路径
        """
        from src.core.tts.qwen3_manager import Qwen3ModelManager

        if output_path is None:
            import tempfile
            temp_dir = Path(tempfile.gettempdir())
            output_path = temp_dir / "clone_preview.wav"

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Step 1: 加载 Base 模型
            print(f"[VoiceDesigner] 加载 Base 模型...")
            base_model = Qwen3ModelManager.get_base_model()

            # Step 2: 创建 voice_clone_prompt
            print(f"[VoiceDesigner] 分析音频: {Path(audio_path).name}")
            voice_clone_prompt = base_model.create_voice_clone_prompt(
                ref_audio=str(audio_path),
                ref_text=ref_text,
            )

            # Step 3: 合成音频
            print(f"[VoiceDesigner] 生成试音音频...")
            wavs, sr = base_model.generate_voice_clone(
                text,
                language="chinese",
                voice_clone_prompt=voice_clone_prompt,
            )

            if wavs and len(wavs) > 0:
                audio = wavs[0].astype(np.float32)
                sf.write(str(output_path), audio, sr)
                print(f"[VoiceDesigner] 试音音频已保存: {output_path}")
                return str(output_path)
            else:
                raise RuntimeError("Qwen3-TTS 返回空音频")

        except Exception as e:
            print(f"[VoiceDesigner] 克隆试音失败: {e}")
            raise


def get_voice_designer() -> VoiceDesigner:
    """获取 VoiceDesigner 单例"""
    if not hasattr(get_voice_designer, "_instance"):
        get_voice_designer._instance = VoiceDesigner()
    return get_voice_designer._instance
