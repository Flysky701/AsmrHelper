"""ASMR Helper 自定义异常类

提供统一的异常体系，便于错误处理和调试。
"""

from typing import Optional, Any


class ASMRHelperError(Exception):
    """基础异常类"""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self):
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ModelLoadError(ASMRHelperError):
    """模型加载失败"""

    pass


class ASRError(ASMRHelperError):
    """ASR 识别失败"""

    def __init__(self, message: str, audio_file: Optional[str] = None):
        super().__init__(message)
        self.audio_file = audio_file


class TranslationError(ASMRHelperError):
    """翻译失败"""

    def __init__(self, message: str, original_text: str = "", index: int = -1):
        super().__init__(message)
        self.original_text = original_text
        self.index = index


class TTSError(ASMRHelperError):
    """TTS 合成失败"""

    def __init__(self, message: str, text: str = "", voice: str = ""):
        super().__init__(message)
        self.text = text
        self.voice = voice


class MixerError(ASMRHelperError):
    """混音失败"""

    pass


class ConfigError(ASMRHelperError):
    """配置错误"""

    pass


class ValidationError(ASMRHelperError):
    """数据验证失败"""

    pass


class ResourceError(ASMRHelperError):
    """资源相关错误（GPU、内存、磁盘等）"""

    pass


class PipelineError(ASMRHelperError):
    """流水线执行错误"""

    def __init__(self, message: str, step: str = "", recoverable: bool = False):
        super().__init__(message)
        self.step = step
        self.recoverable = recoverable
