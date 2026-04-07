"""
ThemeManager - GUI 主题管理器
统一管理暗色主题、QSS 样式表和设计令牌
"""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QFile, QTextStream
from PySide6.QtGui import QColor, QPalette


class ThemeColors:
    """设计颜色令牌"""
    
    # === 主色调 ===
    PRIMARY = "#0078D4"
    PRIMARY_HOVER = "#1a86dd"
    PRIMARY_PRESSED = "#005a9e"
    
    # === 功能色 ===
    SUCCESS = "#107C10"
    SUCCESS_HOVER = "#1a9c1a"
    WARNING = "#FF8C00"
    DANGER = "#D13438"
    INFO = "#569CD6"
    PURPLE = "#8E44AD"
    
    # === 背景色阶（暗色主题）===
    BG_BASE = "#1E1E1E"
    BG_SURFACE = "#252526"
    BG_ELEVATED = "#2D2D30"
    BG_HOVER = "#383838"
    BG_ACTIVE = "#094771"
    
    # === 文字色阶 ===
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#CCCCCC"
    TEXT_DISABLED = "#6A6A6A"
    TEXT_ACCENT = "#4EC970"
    TEXT_ERROR = "#F14C14"
    TEXT_WARNING = "#FF8C00"
    
    # === 边框与分割 ===
    BORDER_SUBTLE = "#3E3E42"
    BORDER_NORMAL = "#5A5A5E"
    BORDER_FOCUS = "#0078D4"
    
    # === 步骤专属色 ===
    STEP_SEPARATION = "#569CD6"
    STEP_ASR = "#4EC970"
    STEP_TRANSLATE = "#DCDCAA"
    STEP_TTS = "#CE9178"
    STEP_MIX = "#C586C0"
    
    # 步骤颜色映射
    STEP_COLORS = {
        "separation": STEP_SEPARATION,
        "asr": STEP_ASR,
        "translate": STEP_TRANSLATE,
        "tts": STEP_TTS,
        "mix": STEP_MIX,
    }


class ThemeFonts:
    """字体规格"""
    
    FONT_FAMILY = "'Microsoft YaHei UI', 'Segoe UI', sans-serif"
    MONO_FONT = "'Consolas', 'Cascadia Code', monospace"
    
    # 字号规格
    DISPLAY_SIZE = "18px"
    HEADING_SIZE = "13px"
    SUBHEADING_SIZE = "12px"
    BODY_SIZE = "11px"
    CAPTION_SIZE = "10px"


class ThemeSpacing:
    """间距系统"""
    
    XS = "4px"
    SM = "8px"
    MD = "12px"
    LG = "16px"
    XL = "24px"


class ThemeManager:
    """GUI 主题管理器（单例）"""
    
    _instance = None
    
    def __init__(self):
        self._app: Optional[QApplication] = None
        self._current_theme = "default_dark"
        self._qss_loaded = False
    
    @classmethod
    def instance(cls) -> 'ThemeManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def apply(self, app: QApplication, theme_name: str = "default_dark") -> None:
        """
        应用主题到 QApplication
        
        Args:
            app: QApplication 实例
            theme_name: 主题名称（不含扩展名）
        """
        self._app = app
        self._current_theme = theme_name
        
        # 1. 设置 Fusion 风格作为基础
        from PySide6.QtWidgets import QStyleFactory
        app.setStyle(QStyleFactory.create("Fusion"))
        
        # 2. 设置暗色调色板
        palette = self._create_dark_palette()
        app.setPalette(palette)
        
        # 3. 加载 QSS 样式表
        self._load_qss(app, theme_name)
        
        # 4. 设置全局 Tooltip 样式
        self._apply_tooltip_style(app)
        
        self._qss_loaded = True
    
    def _load_qss(self, app: QApplication, theme_name: str) -> None:
        """加载 QSS 样式表文件"""
        # 尝试从多个位置查找 QSS 文件
        possible_paths = [
            Path(__file__).parent / f"{theme_name}.qss",
            Path(__file__).parent.parent / "themes" / f"{theme_name}.qss",
        ]
        
        qss_path = None
        for path in possible_paths:
            if path.exists():
                qss_path = path
                break
        
        if qss_path and qss_path.exists():
            with open(qss_path, 'r', encoding='utf-8') as f:
                qss = f.read()
                app.setStyleSheet(qss)
        else:
            # 如果 QSS 文件不存在，使用内联样式
            inline_qss = self._get_inline_qss()
            app.setStyleSheet(inline_qss)
    
    def _get_inline_qss(self) -> str:
        """获取内联 QSS 样式（当文件不存在时的后备方案）"""
        return f"""
        /* 全局样式 */
        QWidget {{
            background-color: {ThemeColors.BG_BASE};
            color: {ThemeColors.TEXT_SECONDARY};
            font-family: {ThemeFonts.FONT_FAMILY};
            font-size: {ThemeFonts.BODY_SIZE};
        }}
        
        QMainWindow {{
            background-color: {ThemeColors.BG_BASE};
        }}
        
        QLabel {{
            background-color: transparent;
            color: {ThemeColors.TEXT_SECONDARY};
        }}
        
        QGroupBox {{
            background-color: {ThemeColors.BG_SURFACE};
            border: 1px solid {ThemeColors.BORDER_SUBTLE};
            border-radius: 6px;
            margin-top: 12px;
            padding: 12px;
            font-weight: 600;
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 2px 8px;
            color: {ThemeColors.TEXT_PRIMARY};
        }}
        """
    
    def _create_dark_palette(self) -> QPalette:
        """创建暗色 QPalette"""
        palette = QPalette()
        
        # 窗口背景
        palette.setColor(QPalette.ColorRole.Window, QColor(ThemeColors.BG_BASE))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(ThemeColors.TEXT_PRIMARY))
        
        # 控件基底
        palette.setColor(QPalette.ColorRole.Base, QColor(ThemeColors.BG_SURFACE))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(ThemeColors.BG_ELEVATED))
        
        # 文字
        palette.setColor(QPalette.ColorRole.Text, QColor(ThemeColors.TEXT_SECONDARY))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(ThemeColors.TEXT_PRIMARY))
        
        # 按钮
        palette.setColor(QPalette.ColorRole.Button, QColor(ThemeColors.BG_ELEVATED))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(ThemeColors.TEXT_PRIMARY))
        
        # 高亮/选中
        palette.setColor(QPalette.ColorRole.Highlight, QColor(ThemeColors.BG_ACTIVE))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(ThemeColors.TEXT_PRIMARY))
        
        # 链接
        palette.setColor(QPalette.ColorRole.Link, QColor(ThemeColors.PRIMARY))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(ThemeColors.INFO))
        
        # 禁用态
        palette.setColor(QPalette.ColorRole.Disabled, QPalette.ColorRole.Text, QColor(ThemeColors.TEXT_DISABLED))
        palette.setColor(QPalette.ColorRole.Disabled, QPalette.ColorRole.WindowText, QColor(ThemeColors.TEXT_DISABLED))
        palette.setColor(QPalette.ColorRole.Disabled, QPalette.ColorRole.ButtonText, QColor(ThemeColors.TEXT_DISABLED))
        
        # 阴影
        palette.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))
        
        return palette
    
    def _apply_tooltip_style(self, app: QApplication) -> None:
        """设置全局 Tooltip 样式"""
        tooltip_qss = f"""
        QToolTip {{
            background-color: {ThemeColors.BG_HOVER};
            color: {ThemeColors.TEXT_PRIMARY};
            border: 1px solid {ThemeColors.BORDER_NORMAL};
            border-radius: 4px;
            padding: 6px 10px;
            font-size: {ThemeFonts.BODY_SIZE};
        }}
        """
        app.setStyleSheet(app.styleSheet() + tooltip_qss)
    
    def get_color(self, token: str) -> str:
        """
        获取颜色令牌值
        
        Args:
            token: 颜色令牌名称（如 'primary', 'success', 'bg_base'）
            
        Returns:
            十六进制颜色代码
        """
        color_map = {
            # 主色调
            'primary': ThemeColors.PRIMARY,
            'primary_hover': ThemeColors.PRIMARY_HOVER,
            'primary_pressed': ThemeColors.PRIMARY_PRESSED,
            
            # 功能色
            'success': ThemeColors.SUCCESS,
            'warning': ThemeColors.WARNING,
            'danger': ThemeColors.DANGER,
            'info': ThemeColors.INFO,
            'purple': ThemeColors.PURPLE,
            
            # 背景色
            'bg_base': ThemeColors.BG_BASE,
            'bg_surface': ThemeColors.BG_SURFACE,
            'bg_elevated': ThemeColors.BG_ELEVATED,
            'bg_hover': ThemeColors.BG_HOVER,
            'bg_active': ThemeColors.BG_ACTIVE,
            
            # 文字色
            'text_primary': ThemeColors.TEXT_PRIMARY,
            'text_secondary': ThemeColors.TEXT_SECONDARY,
            'text_disabled': ThemeColors.TEXT_DISABLED,
            'text_accent': ThemeColors.TEXT_ACCENT,
            'text_error': ThemeColors.TEXT_ERROR,
            'text_warning': ThemeColors.TEXT_WARNING,
            
            # 边框
            'border_subtle': ThemeColors.BORDER_SUBTLE,
            'border_normal': ThemeColors.BORDER_NORMAL,
            'border_focus': ThemeColors.BORDER_FOCUS,
            
            # 步骤色
            'step_separation': ThemeColors.STEP_SEPARATION,
            'step_asr': ThemeColors.STEP_ASR,
            'step_translate': ThemeColors.STEP_TRANSLATE,
            'step_tts': ThemeColors.STEP_TTS,
            'step_mix': ThemeColors.STEP_MIX,
        }
        
        return color_map.get(token.lower(), ThemeColors.TEXT_PRIMARY)
    
    def get_step_color(self, step_name: str) -> str:
        """获取步骤专属颜色"""
        return ThemeColors.STEP_COLORS.get(step_name.lower(), ThemeColors.INFO)
