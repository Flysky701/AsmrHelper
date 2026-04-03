#!/usr/bin/env python
"""
Qwen3-TTS 音色预生成脚本

功能：
1. 使用 VoiceDesign 模型根据自然语言描述生成参考音频
2. 使用 Base 模型创建 voice_clone_prompt 缓存
3. 更新 voice_profiles.json 的 generated 字段

用法：
    uv run python scripts/generate_voice_profiles.py          # 生成所有自定义音色
    uv run python scripts/generate_voice_profiles.py B1      # 只生成 B1
    uv run python scripts/generate_voice_profiles.py --check # 检查生成状态
"""

import sys
import os
import torch
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# 参考文本（用于生成音色参考音频）
REF_TEXT = "你好，今天辛苦了，让我来帮你放松一下吧。"


def get_profile_manager():
    """获取音色管理器"""
    from src.core.tts.voice_profile import get_voice_manager
    return get_voice_manager()


def ensure_models():
    """确保所需模型已下载"""
    from src.core.tts.qwen3_manager import Qwen3ModelManager

    models_dir = project_root / "models" / "qwen3tts"
    os.environ["HF_HOME"] = str(models_dir)

    print("\n[1/4] 检查模型下载状态...")

    # VoiceDesign 模型
    voice_design_path = models_dir / "models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    if not voice_design_path.exists():
        print(f"  - VoiceDesign 模型未下载，请先运行: huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
        return False
    print(f"  - VoiceDesign: OK")

    # Base 模型
    base_path = models_dir / "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base"
    if not base_path.exists():
        print(f"  - Base 模型未下载，请先运行: huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base")
        return False
    print(f"  - Base: OK")

    return True


def generate_voice_profile(profile_id: str, design_instruct: str, output_dir: Path, progress_callback=None):
    """
    生成单个音色配置

    Args:
        profile_id: 音色 ID (B1-B4)
        design_instruct: VoiceDesign 自然语言描述
        output_dir: 输出目录
        progress_callback: 进度回调

    Returns:
        bool: 是否成功
    """
    from src.core.tts.qwen3_manager import Qwen3ModelManager

    output_dir.mkdir(parents=True, exist_ok=True)
    ref_audio_path = output_dir / f"{profile_id}_ref.wav"
    prompt_cache_path = output_dir / f"{profile_id}_prompt.pt"

    def update_progress(msg, progress=None):
        if progress_callback:
            progress_callback(msg, progress)
        print(f"  {msg}")

    try:
        import soundfile as sf

        # Step 1: 使用 VoiceDesign 模型生成参考音频
        update_progress(f"[{profile_id}] 使用 VoiceDesign 生成参考音频...", 10)

        voice_design_model = Qwen3ModelManager.get_voice_design_model()
        update_progress(f"[{profile_id}] 生成中（这可能需要几分钟）...", 20)

        # VoiceDesign 使用 generate_voice_design() 方法
        ref_wavs, sr = voice_design_model.generate_voice_design(
            text=REF_TEXT,
            language="Chinese",
            instruct=design_instruct,
        )
        sf.write(str(ref_audio_path), ref_wavs[0], sr)
        update_progress(f"[{profile_id}] 参考音频已生成: {ref_audio_path}", 50)

        # Step 2: 使用 Base 模型创建 voice_clone_prompt
        update_progress(f"[{profile_id}] 使用 Base 模型创建 prompt...", 60)

        base_model = Qwen3ModelManager.get_base_model()

        # 读取参考音频
        audio, audio_sr = sf.read(str(ref_audio_path))

        # 创建 voice clone prompt（使用 create_voice_clone_prompt）
        prompt = base_model.create_voice_clone_prompt(
            ref_audio=(audio, audio_sr),
            ref_text=REF_TEXT,
            x_vector_only_mode=False,
        )
        update_progress(f"[{profile_id}] prompt 已创建", 80)

        # 保存 prompt 缓存
        torch.save(prompt, str(prompt_cache_path))
        update_progress(f"[{profile_id}] prompt 已缓存: {prompt_cache_path}", 90)

        # 卸载 VoiceDesign 模型（释放显存）
        Qwen3ModelManager.unload("voice_design")

        return True

    except Exception as e:
        print(f"  [{profile_id}] 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Qwen3-TTS 音色预生成工具")
    parser.add_argument("profile_id", nargs="?", help="指定要生成的音色 ID (如 B1)")
    parser.add_argument("--check", action="store_true", help="检查生成状态")
    args = parser.parse_args()

    manager = get_profile_manager()

    # 检查模式
    if args.check:
        print("检查自定义音色生成状态:\n")
        customs = manager.get_customs()
        for p in customs:
            status = "已生成" if p.generated else "未生成"
            ref_exists = Path(p.ref_audio).exists() if p.ref_audio else False
            prompt_exists = Path(p.prompt_cache).exists() if p.prompt_cache else False
            print(f"  {p.id} {p.name}:")
            print(f"    - generated: {status}")
            print(f"    - ref_audio:  {'存在' if ref_exists else '不存在'} ({p.ref_audio})")
            print(f"    - prompt_cache: {'存在' if prompt_exists else '不存在'} ({p.prompt_cache})")
        return

    # 检查模型
    if not ensure_models():
        print("\n请先下载所需的模型！")
        print("运行以下命令下载:")
        print("  huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
        print("  huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base")
        sys.exit(1)

    # 输出目录
    output_dir = project_root / "models" / "voice_profiles"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 选择要生成的音色
    if args.profile_id:
        # 只生成指定的音色
        profile = manager.get_by_id(args.profile_id)
        if not profile:
            print(f"错误: 未找到音色 {args.profile_id}")
            sys.exit(1)
        if profile.category != "custom":
            print(f"错误: {args.profile_id} 不是自定义音色")
            sys.exit(1)
        profiles_to_generate = [profile]
    else:
        # 生成所有未生成的自定义音色
        profiles_to_generate = [p for p in manager.get_customs() if not p.generated]

    if not profiles_to_generate:
        print("所有自定义音色都已生成完成！")
        return

    print(f"\n将生成 {len(profiles_to_generate)} 个音色配置:")
    for p in profiles_to_generate:
        print(f"  - {p.id} {p.name}: {p.design_instruct[:30]}...")

    print("\n" + "="*60)
    print("开始生成（这可能需要 10-30 分钟，请耐心等待...）")
    print("="*60 + "\n")

    success_count = 0
    for i, profile in enumerate(profiles_to_generate):
        print(f"\n[{i+1}/{len(profiles_to_generate)}] 处理 {profile.id} {profile.name}...")

        # 生成音色
        success = generate_voice_profile(
            profile.id,
            profile.design_instruct,
            output_dir,
        )

        if success:
            # 更新配置文件
            ref_audio = str(output_dir / f"{profile.id}_ref.wav")
            prompt_cache = str(output_dir / f"{profile.id}_prompt.pt")
            manager.update_generated(profile.id, True, ref_audio, prompt_cache)
            print(f"  {profile.id} {profile.name} 生成完成！")
            success_count += 1
        else:
            print(f"  {profile.id} {profile.name} 生成失败！")

    print("\n" + "="*60)
    print(f"生成完成: {success_count}/{len(profiles_to_generate)} 成功")
    print("="*60)


if __name__ == "__main__":
    main()
