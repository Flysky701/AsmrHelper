"""
音色工坊功能测试集 (Report 17+)

测试范围:
1. VoiceDesigner 服务层
2. VoiceProfileManager 扩展
3. GUI Worker 线程
4. 集成测试
"""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestVoiceProfileManager:
    """测试 VoiceProfileManager 扩展功能"""

    @pytest.fixture
    def temp_config(self):
        """临时配置文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"version": 1, "profiles": []}, f)
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink(missing_ok=True)

    @pytest.fixture
    def manager(self, temp_config):
        """创建管理器实例"""
        from src.core.tts.voice_profile import VoiceProfileManager
        return VoiceProfileManager(temp_config)

    def test_add_custom_profile(self, manager):
        """测试添加自定义音色"""
        profile_id = manager.add_custom_profile(
            name="测试音色",
            description="用于测试的音色",
            design_instruct="温柔的女声",
            ref_audio="/tmp/test_ref.wav",
            prompt_cache="/tmp/test_prompt.pt"
        )

        assert profile_id.startswith("B")
        profile = manager.get_by_id(profile_id)
        assert profile is not None
        assert profile.name == "测试音色"
        assert profile.category == "custom"
        assert profile.generated is True

    def test_add_clone_profile(self, manager):
        """测试添加克隆音色"""
        profile_id = manager.add_clone_profile(
            name="克隆音色",
            ref_audio="/tmp/clone.wav",
            description="克隆测试"
        )

        assert profile_id.startswith("C")
        profile = manager.get_by_id(profile_id)
        assert profile.category == "clone"

    def test_delete_profile(self, manager):
        """测试删除音色"""
        # 添加一个自定义音色
        profile_id = manager.add_custom_profile(
            name="待删除",
            description="",
            design_instruct=""
        )

        # 删除成功
        assert manager.delete_profile(profile_id) is True
        assert manager.get_by_id(profile_id) is None

        # 删除不存在的音色
        assert manager.delete_profile("B999") is False

    def test_cannot_delete_preset(self, manager):
        """测试不能删除预设音色"""
        # 手动添加一个预设音色
        from src.core.tts.voice_profile import VoiceProfile
        manager._profiles["A1"] = VoiceProfile(
            id="A1",
            name="预设",
            category="preset",
            engine="qwen3_custom",
            speaker="Vivian"
        )

        assert manager.delete_profile("A1") is False

    def test_thread_safety(self, manager):
        """测试线程安全"""
        import threading
        results = []

        def add_profiles():
            for i in range(10):
                pid = manager.add_custom_profile(
                    name=f"音色{i}",
                    description="",
                    design_instruct=""
                )
                results.append(pid)

        # 并发添加
        threads = [threading.Thread(target=add_profiles) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 检查没有重复ID
        assert len(results) == len(set(results))


class TestVoiceDesigner:
    """测试 VoiceDesigner 服务层"""

    @pytest.fixture
    def temp_output_dir(self):
        """临时输出目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def designer(self, temp_output_dir):
        """创建设计师实例"""
        from src.core.tts.voice_designer import VoiceDesigner
        return VoiceDesigner(temp_output_dir)

    def test_voice_templates_exist(self):
        """测试预设模板存在"""
        from src.core.tts.voice_designer import VOICE_TEMPLATES

        required_templates = [
            "治愈大姐姐",
            "娇小萝莉",
            "冷艳女王",
            "邻家女孩",
            "磁性低音"
        ]

        for template in required_templates:
            assert template in VOICE_TEMPLATES
            assert len(VOICE_TEMPLATES[template]) > 0

    def test_progress_callback(self, designer):
        """测试进度回调"""
        progress_calls = []

        def callback(msg, percent):
            progress_calls.append((msg, percent))

        # 模拟设计流程
        designer._report_progress(callback, "测试消息", 50)

        assert len(progress_calls) == 1
        assert progress_calls[0] == ("测试消息", 50)

    @patch('src.core.tts.voice_designer.Qwen3ModelManager')
    @patch('src.core.tts.voice_designer.get_voice_manager')
    def test_design_and_generate_flow(self, mock_get_manager, mock_model_manager, designer, temp_output_dir):
        """测试设计流程"""
        # Mock 模型
        mock_model = MagicMock()
        mock_model.generate_voice_design.return_value = ([MagicMock()], 24000)
        mock_model.create_voice_clone_prompt.return_value = MagicMock()

        mock_model_manager.get_voice_design_model.return_value = mock_model
        mock_model_manager.get_base_model.return_value = mock_model

        # Mock 管理器
        mock_manager = MagicMock()
        mock_manager.get_all.return_value = []
        mock_manager._profiles_lock = MagicMock()
        mock_manager._profiles = {}
        mock_get_manager.return_value = mock_manager

        # 执行设计
        with patch('soundfile.write') as mock_sf_write:
            with patch('torch.save') as mock_torch_save:
                profile = designer.design_and_generate(
                    description="温柔的女声",
                    name="测试音色",
                    ref_text="测试文本"
                )

        # 验证流程
        mock_model_manager.get_voice_design_model.assert_called_once()
        mock_model.generate_voice_design.assert_called_once()
        mock_model_manager.unload.assert_called_once_with("voice_design")
        mock_model_manager.get_base_model.assert_called_once()
        mock_model.create_voice_clone_prompt.assert_called_once()

    @patch('src.core.tts.voice_designer.Qwen3ModelManager')
    @patch('src.core.tts.voice_designer.get_voice_manager')
    def test_clone_from_audio_flow(self, mock_get_manager, mock_model_manager, designer, temp_output_dir):
        """测试克隆流程"""
        # 创建虚拟音频文件
        test_audio = Path(temp_output_dir) / "test.wav"
        test_audio.write_bytes(b"fake audio data")

        # Mock 模型
        mock_model = MagicMock()
        mock_model.create_voice_clone_prompt.return_value = MagicMock()
        mock_model_manager.get_base_model.return_value = mock_model

        # Mock 管理器
        mock_manager = MagicMock()
        mock_manager.get_all.return_value = []
        mock_manager._profiles_lock = MagicMock()
        mock_manager._profiles = {}
        mock_get_manager.return_value = mock_manager

        # 执行克隆
        with patch('torch.save') as mock_torch_save:
            profile = designer.clone_from_audio(
                audio_path=str(test_audio),
                name="克隆音色",
                ref_text="测试文本"
            )

        # 验证流程
        mock_model_manager.get_base_model.assert_called_once()
        mock_model.create_voice_clone_prompt.assert_called_once()

    def test_clone_from_nonexistent_audio(self, designer):
        """测试克隆不存在的音频"""
        with pytest.raises(FileNotFoundError):
            designer.clone_from_audio(
                audio_path="/nonexistent/audio.wav",
                name="测试"
            )


class TestGUIWorkers:
    """测试 GUI Worker 线程"""

    @pytest.fixture
    def qt_app(self):
        """创建 Qt 应用"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    @patch('src.gui_workers.VoiceDesigner')
    def test_voice_design_worker(self, mock_designer_class, qt_app):
        """测试 VoiceDesignWorker"""
        from src.gui_workers import VoiceDesignWorker

        # Mock designer
        mock_profile = MagicMock()
        mock_profile.name = "测试音色"
        mock_profile.id = "B1"

        mock_designer = MagicMock()
        mock_designer.design_and_generate.return_value = mock_profile
        mock_designer_class.return_value = mock_designer

        # 创建 worker
        worker = VoiceDesignWorker(
            name="测试音色",
            description="温柔的女声"
        )

        # 收集信号
        progress_signals = []
        finished_signals = []

        worker.progress.connect(lambda msg, pct: progress_signals.append((msg, pct)))
        worker.finished.connect(lambda success, msg, pid: finished_signals.append((success, msg, pid)))

        # 运行
        worker.run()

        # 验证
        mock_designer.design_and_generate.assert_called_once()
        assert len(finished_signals) == 1
        assert finished_signals[0][0] is True  # success

    @patch('src.gui_workers.VoiceDesigner')
    def test_voice_clone_worker(self, mock_designer_class, qt_app):
        """测试 VoiceCloneWorker"""
        from src.gui_workers import VoiceCloneWorker

        mock_profile = MagicMock()
        mock_profile.name = "克隆音色"
        mock_profile.id = "C1"

        mock_designer = MagicMock()
        mock_designer.clone_from_audio.return_value = mock_profile
        mock_designer_class.return_value = mock_designer

        worker = VoiceCloneWorker(
            name="克隆音色",
            audio_path="/tmp/test.wav"
        )

        finished_signals = []
        worker.finished.connect(lambda success, msg, pid: finished_signals.append((success, msg, pid)))

        worker.run()

        mock_designer.clone_from_audio.assert_called_once()
        assert len(finished_signals) == 1
        assert finished_signals[0][0] is True

    @patch('src.gui_workers.VoiceDesigner')
    @patch('src.gui_workers.get_voice_manager')
    def test_voice_preview_worker(self, mock_get_manager, mock_designer_class, qt_app):
        """测试 VoicePreviewWorker"""
        from src.gui_workers import VoicePreviewWorker

        mock_profile = MagicMock()
        mock_manager = MagicMock()
        mock_manager.get_by_id.return_value = mock_profile
        mock_get_manager.return_value = mock_manager

        mock_designer = MagicMock()
        mock_designer.preview_profile.return_value = "/tmp/preview.wav"
        mock_designer_class.return_value = mock_designer

        worker = VoicePreviewWorker(
            profile_id="B1",
            test_text="测试文本"
        )

        finished_signals = []
        worker.finished.connect(lambda success, msg, path: finished_signals.append((success, msg, path)))

        worker.run()

        mock_designer.preview_profile.assert_called_once()
        assert len(finished_signals) == 1
        assert finished_signals[0][0] is True


class TestIntegration:
    """集成测试"""

    def test_profile_id_generation_sequence(self):
        """测试音色 ID 生成序列"""
        from src.core.tts.voice_profile import VoiceProfile, VoiceProfileManager

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"version": 1, "profiles": []}, f)
            temp_path = f.name

        try:
            manager = VoiceProfileManager(temp_path)

            # 按顺序添加
            id1 = manager.add_custom_profile("音色1", "", "")
            id2 = manager.add_custom_profile("音色2", "", "")
            id3 = manager.add_clone_profile("克隆1", "")
            id4 = manager.add_custom_profile("音色3", "", "")

            # 验证序列
            assert id1 == "B1"
            assert id2 == "B2"
            assert id3 == "C1"
            assert id4 == "B3"

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_profile_persistence(self):
        """测试配置持久化"""
        from src.core.tts.voice_profile import VoiceProfileManager

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            # 第一个实例添加配置
            manager1 = VoiceProfileManager(temp_path)
            manager1.add_custom_profile("持久化测试", "描述", "指令")

            # 第二个实例读取
            manager2 = VoiceProfileManager(temp_path)
            profile = manager2.get_by_id("B1")

            assert profile is not None
            assert profile.name == "持久化测试"

        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_description(self):
        """测试空描述"""
        from src.core.tts.voice_designer import VoiceDesigner

        designer = VoiceDesigner()

        # 空描述应该可以执行（由模型决定如何处理）
        # 这里主要测试不会崩溃
        with patch('src.core.tts.voice_designer.Qwen3ModelManager') as mock:
            mock_model = MagicMock()
            mock_model.generate_voice_design.return_value = ([MagicMock()], 24000)
            mock_model.create_voice_clone_prompt.return_value = MagicMock()
            mock.get_voice_design_model.return_value = mock_model
            mock.get_base_model.return_value = mock_model

            with patch('src.core.tts.voice_designer.get_voice_manager') as mock_mgr:
                mock_manager = MagicMock()
                mock_manager.get_all.return_value = []
                mock_manager._profiles_lock = MagicMock()
                mock_manager._profiles = {}
                mock_mgr.return_value = mock_manager

                with patch('soundfile.write'):
                    with patch('torch.save'):
                        profile = designer.design_and_generate(
                            description="",  # 空描述
                            name="空描述测试"
                        )

    def test_special_characters_in_name(self):
        """测试特殊字符名称"""
        from src.core.tts.voice_profile import VoiceProfileManager

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = VoiceProfileManager(temp_path)

            # 各种特殊字符
            special_names = [
                "音色/测试",
                "音色\\\\测试",
                "音色<script>alert(1)</script>",
                "音色\n换行",
                "音色\t制表",
                "音色" * 100,  # 超长名称
            ]

            for name in special_names:
                pid = manager.add_custom_profile(name, "", "")
                profile = manager.get_by_id(pid)
                assert profile.name == name

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_concurrent_access(self):
        """测试并发访问"""
        import threading
        from src.core.tts.voice_profile import VoiceProfileManager

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            manager = VoiceProfileManager(temp_path)
            errors = []

            def worker():
                try:
                    for i in range(20):
                        pid = manager.add_custom_profile(f"并发{i}", "", "")
                        profile = manager.get_by_id(pid)
                        manager.save()
                except Exception as e:
                    errors.append(str(e))

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"并发错误: {errors}"

        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
