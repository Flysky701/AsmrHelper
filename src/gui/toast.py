"""
Toast 通知组件
轻量级浮动通知，支持 info/success/warning/error 四种级别
"""

from typing import Optional

from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QApplication
from PySide6.QtCore import Qt, QTimer, QEasingCurve, QPropertyAnimation, Property
from PySide6.QtGui import QPainter, QColor, QBrush


class ToastNotification(QWidget):
    """
    Toast 通知组件（右上角浮动显示）
    
    Usage:
        ToastNotification.show_toast(self, "操作成功", "success", 3000)
    """
    
    LEVELS = {
        "info": {"bg": "#094771", "icon": "ℹ", "text": "#FFFFFF"},
        "success": {"bg": "#107C10", "icon": "✓", "text": "#FFFFFF"},
        "warning": {"bg": "#FF8C00", "icon": "⚠", "text": "#FFFFFF"},
        "error": {"bg": "#D13438", "icon": "✗", "text": "#FFFFFF"},
    }
    
    def __init__(
        self,
        parent: QWidget,
        message: str,
        level: str = "info",
        duration: int = 3000
    ):
        super().__init__(parent)
        
        self._duration = duration
        self._level = level
        self._opacity = 0
        
        # 设置窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(320)
        
        # 获取样式
        style = self.LEVELS.get(level, self.LEVELS["info"])
        
        # 设置样式
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {style['bg']};
                border-radius: 6px;
                padding: 12px 16px;
            }}
        """)
        
        # 布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        
        # 图标
        icon_label = QLabel(style['icon'])
        icon_label.setStyleSheet(f"""
            QLabel {{
                font-size: 18px;
                color: {style['text']};
                background: transparent;
            }}
        """)
        layout.addWidget(icon_label)
        
        # 消息文本
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"""
            QLabel {{
                color: {style['text']};
                font-size: 12px;
                font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
                background: transparent;
            }}
        """)
        layout.addWidget(msg_label, stretch=1)
        
        # 调整大小
        self.adjustSize()
        
        # 初始位置（屏幕右上角）
        self._move_to_corner()
    
    def _move_to_corner(self):
        """移动到屏幕右上角"""
        from PySide6.QtWidgets import QApplication, QDesktopWidget
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            x = screen_geometry.right() - self.width() - 20
            y = screen_geometry.top() + 20
            self.move(x, y)
    
    def _get_opacity(self) -> float:
        return self._opacity
    
    def _set_opacity(self, value: float):
        self._opacity = value
        self.setWindowOpacity(value)
    
    _opacity_property = Property(float, _get_opacity, _set_opacity)
    
    def show_temporarily(self, duration: int = None):
        """
        显示通知并自动隐藏
        
        Args:
            duration: 显示时长（毫秒），默认使用构造时的值
        """
        if duration is None:
            duration = self._duration
        
        self.show()
        
        # 淡入动画
        fade_in = QPropertyAnimation(self, b"_opacity")
        fade_in.setDuration(200)
        fade_in.setStartValue(0)
        fade_in.setEndValue(1)
        fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # 等待一段时间
        wait_timer = QTimer(self)
        wait_timer.setSingleShot(True)
        wait_timer.timeout.connect(lambda: self._fade_out())
        wait_timer.start(duration)
        
        fade_in.start()
        
        # 保存动画引用防止被垃圾回收
        self._fade_in_anim = fade_in
    
    def _fade_out(self):
        """淡出动画"""
        fade_out = QPropertyAnimation(self, b"_opacity")
        fade_out.setDuration(200)
        fade_out.setStartValue(1)
        fade_out.setEndValue(0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_out.finished.connect(self.close)
        fade_out.finished.connect(self.deleteLater)
        fade_out.start()
        
        # 保存动画引用
        self._fade_out_anim = fade_out
    
    @staticmethod
    def show_toast(
        parent: QWidget,
        message: str,
        level: str = "info",
        duration: int = 3000
    ):
        """
        静态方法：在父窗口右上角显示 Toast 通知
        
        Args:
            parent: 父窗口
            message: 通知消息
            level: 通知级别 (info/success/warning/error)
            duration: 显示时长（毫秒）
        """
        toast = ToastNotification(parent, message, level, duration)
        toast.show_temporarily(duration)
