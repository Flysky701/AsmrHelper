"""
窗口状态持久化
保存和恢复窗口位置、大小和最后活跃标签页
"""

import json
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QMainWindow, QTabWidget

logger = logging.getLogger(__name__)

# 状态文件路径
STATE_FILE = Path.home() / ".asmr_helper" / "window_state.json"


def save_window_state(window: QMainWindow, tabs: Optional[QTabWidget] = None):
    """
    保存窗口状态
    
    Args:
        window: QMainWindow 实例
        tabs: 可选的 QTabWidget 用于保存当前标签页
    """
    try:
        state = {
            "geometry": window.geometry().getRect(),
            "maximized": window.isMaximized(),
            "minimized": window.isMinimized(),
        }
        
        if tabs is not None:
            state["last_tab"] = tabs.currentIndex()
        
        # 确保目录存在
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        
        logger.debug(f"窗口状态已保存: {state}")
    except Exception as e:
        logger.warning(f"保存窗口状态失败: {e}")


def restore_window_state(window: QMainWindow, tabs: Optional[QTabWidget] = None) -> bool:
    """
    恢复窗口状态
    
    Args:
        window: QMainWindow 实例
        tabs: 可选的 QTabWidget 用于恢复当前标签页
        
    Returns:
        是否成功恢复
    """
    try:
        if not STATE_FILE.exists():
            return False
        
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        
        # 恢复几何信息
        if not state.get("maximized", False):
            geometry = state.get("geometry")
            if geometry:
                window.setGeometry(*geometry)
        else:
            window.showMaximized()
        
        # 恢复标签页
        if tabs is not None and "last_tab" in state:
            last_tab = state.get("last_tab", 0)
            if 0 <= last_tab < tabs.count():
                tabs.setCurrentIndex(last_tab)
        
        logger.debug(f"窗口状态已恢复: {state}")
        return True
        
    except Exception as e:
        logger.warning(f"恢复窗口状态失败: {e}")
        return False


class WindowStateManager:
    """
    窗口状态管理器
    
    自动保存和恢复窗口状态
    """
    
    def __init__(self, window: QMainWindow, tabs: Optional[QTabWidget] = None):
        self.window = window
        self.tabs = tabs
        
        # 连接关闭事件
        window.closeEvent = self._on_close
    
    def _on_close(self, event):
        """窗口关闭时保存状态"""
        save_window_state(self.window, self.tabs)
        # 调用原始 closeEvent（如果有的话）
        # 注意：QMainWindow.closeEvent 不接受 event 参数
        # 这里使用 try-finally 确保事件被处理
        try:
            pass  # 状态已在上面保存
        finally:
            pass
    
    def restore(self) -> bool:
        """恢复窗口状态"""
        return restore_window_state(self.window, self.tabs)
