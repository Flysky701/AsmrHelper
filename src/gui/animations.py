"""
动画工具集
提供通用动画效果
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QVariantAnimation
from PySide6.QtWidgets import QWidget, QGraphicsOpacityEffect
from PySide6.QtGui import QColor, QPalette


class AnimationHelper:
    """动画工具集"""
    
    @staticmethod
    def fade_in(widget: QWidget, duration_ms: int = 200):
        """
        淡入动画
        
        Args:
            widget: 目标控件
            duration_ms: 动画时长（毫秒）
        """
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(duration_ms)
        anim.setStartValue(0)
        anim.setEndValue(1)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        
        return anim
    
    @staticmethod
    def fade_out(widget: QWidget, duration_ms: int = 200, on_finished=None):
        """
        淡出动画
        
        Args:
            widget: 目标控件
            duration_ms: 动画时长（毫秒）
            on_finished: 动画完成后的回调
        """
        effect = widget.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(duration_ms)
        anim.setStartValue(1)
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        
        if on_finished:
            anim.finished.connect(on_finished)
        
        anim.start()
        return anim
    
    @staticmethod
    def pulse_border(widget: QWidget, color: str = "#0078D4", duration_ms: int = 1500):
        """
        边框脉冲效果（用于执行中状态提示）
        
        Args:
            widget: 目标控件
            color: 边框颜色
            duration_ms: 动画周期（毫秒）
        """
        anim = QVariantAnimation()
        anim.setDuration(duration_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.setLoopCount(-1)  # 无限循环
        
        def update_border(value):
            # 在0和1之间交替实现脉冲效果
            opacity = abs(0.5 - value) * 2
            widget.setStyleSheet(f"""
                QWidget {{
                    border: 2px solid {color};
                    border-radius: 4px;
                    opacity: {0.5 + opacity * 0.5};
                }}
            """)
        
        anim.valueChanged.connect(update_border)
        anim.start()
        
        return anim
    
    @staticmethod
    def color_transition(
        widget: QWidget,
        start_color: str,
        end_color: str,
        property_name: str = "background-color",
        duration_ms: int = 300
    ):
        """
        颜色过渡动画
        
        Args:
            widget: 目标控件
            start_color: 起始颜色
            end_color: 结束颜色
            property_name: CSS 属性名
            duration_ms: 动画时长
        """
        start = QColor(start_color)
        end = QColor(end_color)
        
        anim = QVariantAnimation()
        anim.setDuration(duration_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        def update_color(value):
            r = int(start.red() + (end.red() - start.red()) * value)
            g = int(start.green() + (end.green() - start.green()) * value)
            b = int(start.blue() + (end.blue() - start.blue()) * value)
            current = f"rgb({r}, {g}, {b})"
            widget.setStyleSheet(f"{property_name}: {current};")
        
        anim.valueChanged.connect(update_color)
        anim.start()
        
        return anim
    
    @staticmethod
    def flash_success(widget: QWidget, duration_ms: int = 500):
        """
        成功闪烁效果（绿色背景短暂出现后消失）
        
        Args:
            widget: 目标控件
            duration_ms: 闪烁时长
        """
        from PySide6.QtCore import QTimer
        
        original_style = widget.styleSheet()
        
        # 闪绿
        widget.setStyleSheet(f"{original_style} background-color: rgba(78, 201, 112, 0.3);")
        
        # 延迟恢复
        QTimer.singleShot(duration_ms, lambda: widget.setStyleSheet(original_style))
    
    @staticmethod
    def flash_error(widget: QWidget, duration_ms: int = 500):
        """
        错误闪烁效果（红色边框短暂出现后消失）
        
        Args:
            widget: 目标控件
            duration_ms: 闪烁时长
        """
        from PySide6.QtCore import QTimer
        
        original_style = widget.styleSheet()
        
        # 闪红
        widget.setStyleSheet(f"{original_style} border: 2px solid #D13438;")
        
        # 延迟恢复
        QTimer.singleShot(duration_ms, lambda: widget.setStyleSheet(original_style))
    
    @staticmethod
    def slide_in(widget: QWidget, direction: str = "right", duration_ms: int = 300):
        """
        滑入动画
        
        Args:
            widget: 目标控件
            direction: 滑入方向 (left/right/top/bottom)
            duration_ms: 动画时长
        """
        from PySide6.QtWidgets import QApplication, QDesktopWidget
        
        # 记录原始位置
        original_pos = widget.pos()
        
        # 设置起始位置
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else QDesktopWidget().availableGeometry()
        
        if direction == "left":
            start_pos = original_pos - widget.rect().topRight()
        elif direction == "right":
            start_pos = screen_geo.topRight() + widget.rect().topLeft()
        elif direction == "top":
            start_pos = original_pos - widget.rect().bottomLeft()
        else:  # bottom
            start_pos = screen_geo.bottomLeft() + widget.rect().topLeft()
        
        widget.move(start_pos)
        widget.show()
        
        # 动画移动到原位置
        anim = QPropertyAnimation(widget, b"pos")
        anim.setDuration(duration_ms)
        anim.setStartValue(start_pos)
        anim.setEndValue(original_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        
        return anim


class StepAnimationHelper:
    """步骤相关动画辅助类"""
    
    @staticmethod
    def animate_step_complete(step_widget: QWidget, step_color: str = "#4EC970"):
        """
        步骤完成动画
        
        Args:
            step_widget: 步骤对应的控件
            step_color: 步骤颜色
        """
        AnimationHelper.flash_success(step_widget)
    
    @staticmethod
    def animate_step_error(step_widget: QWidget):
        """步骤失败动画"""
        AnimationHelper.flash_error(step_widget)
    
    @staticmethod
    def animate_step_running(step_widget: QWidget, step_color: str = "#0078D4"):
        """步骤运行中动画"""
        AnimationHelper.pulse_border(step_widget, step_color)
