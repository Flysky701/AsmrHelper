"""
检查点管理器 - 断电续行功能核心模块

功能：
1. 保存流水线执行状态到 checkpoint 文件
2. 从 checkpoint 文件恢复执行状态
3. 检测可恢复的任务
4. 原子写入，防止断电导致文件损坏
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from .pipeline import PipelineState


class CheckpointManager:
    """
    检查点管理器 - 负责流水线状态的持久化和恢复

    使用原子写入（临时文件 + rename）确保断电时不会损坏 checkpoint 文件。
    """

    CHECKPOINT_FILENAME = ".checkpoint.json"
    CHECKPOINT_TMP_FILENAME = ".checkpoint.tmp"

    def __init__(self):
        """初始化检查点管理器"""
        pass

    def save(
        self,
        by_product_dir: str,
        step_name: str,
        state: PipelineState,
    ) -> bool:
        """
        保存检查点

        使用原子写入：
        1. 写入临时文件 .checkpoint.tmp
        2. 重命名为 .checkpoint.json

        Args:
            by_product_dir: 中间文件目录
            step_name: 刚完成的步骤名称
            state: 当前流水线状态

        Returns:
            是否保存成功
        """
        checkpoint_path = Path(by_product_dir) / self.CHECKPOINT_FILENAME
        tmp_path = Path(by_product_dir) / self.CHECKPOINT_TMP_FILENAME

        # 构建检查点数据
        checkpoint_data = {
            "version": 1,
            "task_id": Path(state.input_path).stem,
            "created_at": datetime.now().isoformat(),
            "last_step": step_name,
            "completed_steps": self._get_completed_steps_list(state),
            "state": state.to_dict(),
            "by_product_dir": by_product_dir,
        }

        try:
            # 确保目录存在
            Path(by_product_dir).mkdir(parents=True, exist_ok=True)

            # 写入临时文件
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)

            # 原子重命名
            backup_path = None
            if checkpoint_path.exists():
                backup_path = checkpoint_path.with_suffix(".backup")
                shutil.move(str(checkpoint_path), str(backup_path))

            shutil.move(str(tmp_path), str(checkpoint_path))

            # 删除备份
            if backup_path and backup_path.exists():
                backup_path.unlink()

            return True

        except Exception as e:
            print(f"[CheckpointManager] 保存失败: {e}")
            # 清理临时文件
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return False

    def load(self, by_product_dir: str) -> Optional[Dict[str, Any]]:
        """
        加载检查点

        Args:
            by_product_dir: 中间文件目录

        Returns:
            检查点数据字典，如果不存在则返回 None
        """
        checkpoint_path = Path(by_product_dir) / self.CHECKPOINT_FILENAME

        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 验证版本
            if data.get("version") != 1:
                print(f"[CheckpointManager] 不支持的检查点版本: {data.get('version')}")
                return None

            return data

        except json.JSONDecodeError as e:
            print(f"[CheckpointManager] 检查点文件损坏: {e}")
            return None
        except Exception as e:
            print(f"[CheckpointManager] 加载检查点失败: {e}")
            return None

    def get_resume_info(self, by_product_dir: str) -> Optional[Dict[str, Any]]:
        """
        获取恢复信息（供 GUI 显示）

        Args:
            by_product_dir: 中间文件目录

        Returns:
            包含恢复信息的字典，如果无检查点则返回 None
        """
        checkpoint = self.load(by_product_dir)
        if not checkpoint:
            return None

        completed_steps = checkpoint.get("completed_steps", [])
        last_step = checkpoint.get("last_step", "")

        # 计算下一步
        from .pipeline import STEP_NAMES
        next_step = None
        for step in STEP_NAMES:
            if step not in completed_steps:
                next_step = step
                break

        return {
            "task_id": checkpoint.get("task_id"),
            "completed_steps": completed_steps,
            "last_step": last_step,
            "next_step": next_step,
            "created_at": checkpoint.get("created_at"),
            "state": PipelineState.from_dict(checkpoint.get("state", {})),
        }

    def get_state(self, by_product_dir: str) -> Optional[PipelineState]:
        """
        获取检查点中的状态（用于断点恢复）

        Args:
            by_product_dir: 中间文件目录

        Returns:
            PipelineState 对象，如果无检查点则返回 None
        """
        checkpoint = self.load(by_product_dir)
        if not checkpoint:
            return None

        state_data = checkpoint.get("state", {})
        if not state_data:
            return None

        return PipelineState.from_dict(state_data)

    def clear(self, by_product_dir: str) -> bool:
        """
        清除检查点（重试时使用）

        Args:
            by_product_dir: 中间文件目录

        Returns:
            是否清除成功
        """
        checkpoint_path = Path(by_product_dir) / self.CHECKPOINT_FILENAME

        if not checkpoint_path.exists():
            return True

        try:
            checkpoint_path.unlink()
            return True
        except Exception as e:
            print(f"[CheckpointManager] 清除检查点失败: {e}")
            return False

    def exists(self, by_product_dir: str) -> bool:
        """
        检查是否存在检查点

        Args:
            by_product_dir: 中间文件目录

        Returns:
            是否存在检查点
        """
        checkpoint_path = Path(by_product_dir) / self.CHECKPOINT_FILENAME
        return checkpoint_path.exists()

    def get_pending_tasks(self, search_dirs: List[str]) -> List[Dict[str, Any]]:
        """
        扫描多个目录，查找所有可恢复的任务

        Args:
            search_dirs: 要搜索的目录列表

        Returns:
            可恢复任务列表
        """
        pending = []

        for dir_path in search_dirs:
            by_product_dir = Path(dir_path) / "BY_Product"
            if by_product_dir.exists():
                for task_dir in by_product_dir.iterdir():
                    if task_dir.is_dir():
                        info = self.get_resume_info(str(task_dir))
                        if info:
                            info["by_product_dir"] = str(task_dir)
                            pending.append(info)

        return pending

    def _get_completed_steps_list(self, state: PipelineState) -> List[str]:
        """
        根据状态推断已完成的步骤

        Args:
            state: 流水线状态

        Returns:
            已完成步骤列表
        """
        from .pipeline import STEP_NAMES

        completed = []

        # vocal_path 存在且非原音频 -> separation 完成
        if state.vocal_path and Path(state.vocal_path).name != "vocal.wav":
            # 可能是原音频，需要更精确的判断
            pass
        elif state.vocal_path:
            # 检查是否真的完成了 separation（通过检查是否有 vocal.wav）
            if Path(state.by_product_dir) / "vocal.wav":
                completed.append("separation")

        # 更精确的判断：检查中间文件
        by_product = Path(state.by_product_dir)
        if (by_product / "vocal.wav").exists():
            completed.append("separation")
        if (by_product / "asr_result.txt").exists():
            completed.append("asr")
        if (by_product / "translated.txt").exists():
            completed.append("translate")
        if (by_product / "tts_aligned.wav").exists():
            completed.append("tts")
        if state.mix_output_path and Path(state.mix_output_path).exists():
            completed.append("mix")

        return completed


# 全局单例
_checkpoint_manager: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> CheckpointManager:
    """获取检查点管理器单例"""
    global _checkpoint_manager
    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager()
    return _checkpoint_manager
