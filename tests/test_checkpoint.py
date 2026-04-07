"""
CheckpointManager 单元测试
"""
import pytest
import tempfile
import shutil
from pathlib import Path

from src.core.checkpoint import CheckpointManager
from src.core.pipeline import PipelineState


class TestCheckpointManager:
    """CheckpointManager 测试"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        tmpdir = tempfile.mkdtemp()
        yield Path(tmpdir)
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def checkpoint_manager(self):
        """创建 CheckpointManager 实例"""
        return CheckpointManager()

    @pytest.fixture
    def sample_state(self):
        """创建示例 PipelineState"""
        return PipelineState(
            input_path="/path/to/input.wav",
            by_product_dir="/path/to/output/BY_Product",
            mix_path="/path/to/output/input_mix.wav",
            vocal_path="/path/to/output/BY_Product/vocal.wav",
            asr_results=[{"text": "测试文本"}],
            translations=["测试翻译"],
            timestamped_segments=[
                {"start": 0.0, "end": 1.0, "text": "测试", "translation": "测试翻译"}
            ],
        )

    def test_save_and_load(self, temp_dir, checkpoint_manager, sample_state):
        """测试保存和加载检查点"""
        by_product_dir = str(temp_dir / "BY_Product")

        # 保存检查点
        result = checkpoint_manager.save(
            by_product_dir=by_product_dir,
            step_name="asr",
            state=sample_state,
        )
        assert result is True

        # 加载检查点
        loaded = checkpoint_manager.load(by_product_dir)
        assert loaded is not None
        assert loaded["last_step"] == "asr"
        assert loaded["task_id"] == "input"

    def test_get_resume_info(self, temp_dir, checkpoint_manager, sample_state):
        """测试获取恢复信息"""
        by_product_dir = str(temp_dir / "BY_Product")

        # 保存检查点
        checkpoint_manager.save(
            by_product_dir=by_product_dir,
            step_name="translate",
            state=sample_state,
        )

        # 获取恢复信息
        resume_info = checkpoint_manager.get_resume_info(by_product_dir)
        assert resume_info is not None
        assert resume_info["last_step"] == "translate"
        assert resume_info["next_step"] in ["tts", "mix"]
        assert resume_info["task_id"] == "input"

    def test_get_state(self, temp_dir, checkpoint_manager, sample_state):
        """测试获取检查点状态"""
        by_product_dir = str(temp_dir / "BY_Product")

        # 保存检查点
        checkpoint_manager.save(
            by_product_dir=by_product_dir,
            step_name="separation",
            state=sample_state,
        )

        # 获取状态
        state = checkpoint_manager.get_state(by_product_dir)
        assert state is not None
        assert state.input_path == sample_state.input_path
        assert state.vocal_path == sample_state.vocal_path

    def test_clear(self, temp_dir, checkpoint_manager, sample_state):
        """测试清除检查点"""
        by_product_dir = str(temp_dir / "BY_Product")

        # 保存检查点
        checkpoint_manager.save(
            by_product_dir=by_product_dir,
            step_name="separation",
            state=sample_state,
        )

        # 验证存在
        assert checkpoint_manager.exists(by_product_dir)

        # 清除检查点
        result = checkpoint_manager.clear(by_product_dir)
        assert result is True

        # 验证已删除
        assert not checkpoint_manager.exists(by_product_dir)

    def test_exists(self, temp_dir, checkpoint_manager, sample_state):
        """测试检查点存在性"""
        by_product_dir = str(temp_dir / "BY_Product")

        # 不存在时
        assert not checkpoint_manager.exists(by_product_dir)

        # 保存后
        checkpoint_manager.save(
            by_product_dir=by_product_dir,
            step_name="separation",
            state=sample_state,
        )
        assert checkpoint_manager.exists(by_product_dir)

    def test_no_checkpoint(self, temp_dir, checkpoint_manager):
        """测试无检查点情况"""
        by_product_dir = str(temp_dir / "BY_Product")

        # 加载应返回 None
        assert checkpoint_manager.load(by_product_dir) is None

        # 恢复信息应返回 None
        assert checkpoint_manager.get_resume_info(by_product_dir) is None

        # 状态应返回 None
        assert checkpoint_manager.get_state(by_product_dir) is None

    def test_invalid_checkpoint(self, temp_dir, checkpoint_manager):
        """测试无效检查点"""
        by_product_dir = str(temp_dir / "BY_Product")
        by_product_dir_path = Path(by_product_dir)
        by_product_dir_path.mkdir(parents=True, exist_ok=True)

        # 写入无效 JSON
        invalid_file = by_product_dir_path / CheckpointManager.CHECKPOINT_FILENAME
        invalid_file.write_text("{ invalid json }")

        # 加载应返回 None
        assert checkpoint_manager.load(by_product_dir) is None

    def test_version_mismatch(self, temp_dir, checkpoint_manager):
        """测试版本不匹配"""
        by_product_dir = str(temp_dir / "BY_Product")
        by_product_dir_path = Path(by_product_dir)
        by_product_dir_path.mkdir(parents=True, exist_ok=True)

        # 写入错误版本
        invalid_file = by_product_dir_path / CheckpointManager.CHECKPOINT_FILENAME
        invalid_file.write_text('{"version": 999}')

        # 加载应返回 None
        assert checkpoint_manager.load(by_product_dir) is None


class TestPipelineState:
    """PipelineState 数据类测试"""

    def test_to_dict(self):
        """测试转换为字典"""
        state = PipelineState(
            input_path="/path/to/input.wav",
            vocal_path="/path/to/vocal.wav",
            asr_results=[{"text": "测试"}],
        )

        d = state.to_dict()
        assert d["input_path"] == "/path/to/input.wav"
        assert d["vocal_path"] == "/path/to/vocal.wav"
        assert len(d["asr_results"]) == 1

    def test_from_dict(self):
        """测试从字典恢复"""
        data = {
            "input_path": "/path/to/input.wav",
            "vocal_path": "/path/to/vocal.wav",
            "asr_results": [{"text": "测试"}],
            "translations": ["翻译"],
            "timestamped_segments": [{"start": 0.0, "end": 1.0, "text": "测试", "translation": "翻译"}],
            "tts_path": "",
            "mix_output_path": "",
            "mix_path": "",
            "by_product_dir": "",
            "subtitle_path": None,
            "subtitle_lang": None,
            "cloned_profile_id": None,
        }

        state = PipelineState.from_dict(data)
        assert state.input_path == "/path/to/input.wav"
        assert state.vocal_path == "/path/to/vocal.wav"
        assert len(state.asr_results) == 1
