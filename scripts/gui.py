#!/usr/bin/env python3
"""
ASMR Helper GUI 启动器
"""

import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.gui import main

if __name__ == "__main__":
    main()
