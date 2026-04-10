def fix_code():
    with open('src/gui/views/single_tab.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    start = -1
    end = -1
    for i, line in enumerate(lines):
        if 'edge_voice_widget = QWidget()' in line or ('edge_voice_layout =' in line and 'QVBoxLayout' in line):
            if start == -1:
                start = i
        if '# 初始化：默认显示 Edge-TTS 音色选择器' in line:
            end = i
            break
            
    if start != -1 and end != -1:
        new_block = [
            '            # Edge-TTS 音色选择器 (Index 0)\n',
            '            edge_voice_widget = QWidget()\n',
            '            edge_voice_layout = QVBoxLayout()\n',
            '            edge_voice_layout.addWidget(self.single_edge_voice)\n',
            '            edge_voice_layout.addStretch()\n',
            '            edge_voice_widget.setLayout(edge_voice_layout)\n',
            '            self.single_voice_container.addWidget(edge_voice_widget)\n',
            '\n',
            '            # Qwen3-TTS 音色选择器 (Index 1) - 使用 QStackedWidget + QComboBox 替代 QTabWidget\n',
            '            self.single_qwen3_voice_stack = QStackedWidget()\n',
            '\n',
            '            # Tab 1: 预设音色\n',
            '            self.single_preset_voice = QComboBox()\n',
            '            self.single_preset_voice.addItems([\n',
            '                "Vivian (A1)", "Serena (A2)", "Uncle_Fu (A3)", "Dylan (A4)",\n',
            '                "Eric (A5)", "Ryan (A6)", "Ono_Anna (A7)"\n',
            '            ])\n',
            '            preset_layout = QVBoxLayout()\n',
            '            preset_layout.addWidget(self.single_preset_voice)\n',
            '            preset_layout.addStretch()\n',
            '            preset_widget = QWidget()\n',
            '            preset_widget.setLayout(preset_layout)\n',
            '            self.single_qwen3_voice_stack.addWidget(preset_widget)\n',
            '\n',
            '            # Tab 2: 自定义音色\n',
            '            self.single_custom_voice = QComboBox()\n',
            '            # 初始化时从配置加载，稍后由 _refresh_custom_voice_combos() 填充\n',
            '            custom_layout = QVBoxLayout()\n',
            '            custom_layout.addWidget(self.single_custom_voice)\n',
            '            custom_layout.addWidget(QLabel("（需要先运行预生成脚本）"))\n',
            '            custom_layout.addStretch()\n',
            '            custom_widget = QWidget()\n',
            '            custom_widget.setLayout(custom_layout)\n',
            '            self.single_qwen3_voice_stack.addWidget(custom_widget)\n',
            '\n',
            '            # 音色类型选择器 + QStackedWidget（克隆音色功能已移至"音色工坊"页面）\n',
            '            self.single_voice_type = QComboBox()\n',
            '            self.single_voice_type.addItems(["预设音色", "自定义音色"])\n',
            '            self.single_voice_type.currentIndexChanged.connect(\n',
            '                self.single_qwen3_voice_stack.setCurrentIndex\n',
            '            )\n',
            '            qwen3_voice_widget = QWidget()\n',
            '            qwen3_voice_layout = QVBoxLayout()\n',
            '            qwen3_voice_layout.addWidget(self.single_voice_type)\n',
            '            qwen3_voice_layout.addWidget(self.single_qwen3_voice_stack, 1)  # 拉伸因子=1\n',
            '            qwen3_voice_widget.setLayout(qwen3_voice_layout)\n',
            '            self.single_voice_container.addWidget(qwen3_voice_widget)\n',
            '            # 添加拉伸因子让容器能够正常显示\n',
            '            tts_layout.addWidget(self.single_voice_container, stretch=1)\n',
            '\n',
            '            # 初始化：默认显示 Edge-TTS 音色选择器\n'
        ]
        lines = lines[:start] + new_block + lines[end+1:]
        with open('src/gui/views/single_tab.py', 'w', encoding='utf-8') as f:
            f.writelines(lines)
            print("Fixed single_tab.py")

fix_code()
