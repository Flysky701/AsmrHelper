"""
设计模式工具模块

包含常用的设计模式实现：
- singleton: 线程安全的单例装饰器
"""

import threading
from functools import wraps


def singleton(cls):
    """
    线程安全的单例装饰器

    使用双重检查锁定（Double-Checked Locking）模式，
    确保在多线程环境下安全地创建单例实例。

    用法:
        @singleton
        class MyClass:
            def __init__(self):
                self.value = None

    注意:
        - 类必须有无参数的 __init__ 方法，或所有参数都有默认值
        - 构造函数参数应保持一致（每次调用返回同一实例）
    """
    _instances = {}
    _lock = threading.Lock()

    @wraps(cls)
    def get_instance(*args, **kwargs):
        # 第一次检查：快速路径，避免每次都加锁
        if cls not in _instances:
            with _lock:
                # 第二次检查：确保在加锁期间没有其他线程创建实例
                if cls not in _instances:
                    _instances[cls] = cls(*args, **kwargs)
        return _instances[cls]

    return get_instance
