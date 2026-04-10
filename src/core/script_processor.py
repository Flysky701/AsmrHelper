import re
from typing import List, Dict, Optional, Tuple
from pathlib import Path

class ScriptProcessor:
    """台本预处理管线系统，处理TXT和PDF转字幕前的预处理"""

    # ===== Stage 1: 多脚本检测 =====
    @staticmethod
    def detect_scripts(text: str, source_type: str = "auto") -> List[Dict]:
        """统一的多脚本检测 (TXT/PDF通用)
        Returns: [{"index": int, "title": str, "text": str, "metadata": Dict}, ...]
        """
        # 如果是PDF传入的由于不好确定page_start，这里以文本切分为主
        # 先利用结束标记进行初步切分，再用章节标记
        sections = []
        
        # 尝试使用明确的章节分隔
        boundaries = []  # [(position, title)]

        # 匹配第X話/章/幕，支持全角半角、空格
        for m in re.finditer(r'^[第\s]*([0-9０-９零一二三四五六七八九十百千万]+)[\s\-\.]*[話话章幕回][\s:：]*(.*)$', text, re.MULTILINE):
            title = (m.group(1) + m.group(2)).strip()
            if not title:
                title = f"第{m.group(1)}話"
            boundaries.append((m.start(), title))

        # Chapter/Scene
        for m in re.finditer(r'^(Chapter|SCENE|Part)\s*[\.\s]*(\d+)[:\s]*(.*)$', text, re.IGNORECASE | re.MULTILINE):
            title = f"{m.group(1)} {m.group(2)}".strip()
            rest = m.group(3).strip()
            if rest:
                title += f" - {rest}"
            boundaries.append((m.start(), title))

        # 【标题】或 「标题」 格式
        for m in re.finditer(r'^【([^】]+)】', text, re.MULTILINE):
            boundaries.append((m.start(), m.group(1)))
            
        # Markdown 标题 ## xxx
        for m in re.finditer(r'^#{1,3}\s+(.+)$', text, re.MULTILINE):
            boundaries.append((m.start(), m.group(1).strip()))

        boundaries.sort(key=lambda x: x[0])

        if boundaries:
            for i in range(len(boundaries)):
                start_pos, title = boundaries[i]
                end_pos = boundaries[i+1][0] if i + 1 < len(boundaries) else len(text)
                section_text = text[start_pos:end_pos].strip()
                if section_text:
                    sections.append({
                        "index": i,
                        "title": title,
                        "text": section_text,
                        "metadata": {}
                    })
        
        if not sections:
            # 尝试用长空行分隔
            long_gap_pattern = re.compile(r'\n{4,}')
            gap_matches = list(long_gap_pattern.finditer(text))
            
            if len(gap_matches) >= 1:
                start_pos = 0
                for i, m in enumerate(gap_matches):
                    end_pos = m.start()
                    section_text = text[start_pos:end_pos].strip()
                    if section_text:
                        sections.append({
                            "index": len(sections),
                            "title": f"Part {len(sections) + 1}",
                            "text": section_text,
                            "metadata": {}
                        })
                    start_pos = m.end()
                
                # 最后一个
                section_text = text[start_pos:].strip()
                if section_text:
                    sections.append({
                        "index": len(sections),
                        "title": f"Part {len(sections) + 1}",
                        "text": section_text,
                        "metadata": {}
                    })
                    
        if not sections:
            # 只有一个台本
            sections.append({
                "index": 0,
                "title": "默认台本",
                "text": text,
                "metadata": {}
            })
            
        return sections

    @staticmethod
    def split_by_end_markers(text: str) -> List[str]:
        """按 (第X話　終わり) 等显式结束标记切分"""
        pattern = re.compile(r'（.*?終わり.*?）|\(.*?終わり.*?\)|\<.*?終わり.*?\>')
        parts = []
        last_end = 0
        for m in pattern.finditer(text):
            part = text[last_end:m.end()].strip()
            if part:
                parts.append(part)
            last_end = m.end()
        if last_end < len(text) and text[last_end:].strip():
            parts.append(text[last_end:].strip())
        
        return parts if parts else [text]

    # ===== Stage 2: 竖排→横排 =====
    @staticmethod
    def convert_vertical_to_horizontal(text: str) -> str:
        """简单的竖排转横排尝试（通常是从右到左列的提取）
        如果已经是横排则不做处理，假定已经通过竖排检测
        这里主要是将由于复制PDF竖排格式导致的字符交叉问题修复或换行合并"""
        # 对于简单的断行合并（因为竖排常常固定宽度）
        lines = text.splitlines()
        if not lines:
            return text
            
        # 此处实现极简版本：如果行非常短，尝试连接相邻非空行，这在很多场景不是真正的竖排恢复
        # 完整的 OCR/PDF 竖排恢复非常复杂，我们采用简单的段落重组：
        # 如果当前行没有标点结尾，且下一行开头也是文字，则合并
        merged = []
        current_para = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_para:
                    merged.append("".join(current_para))
                    current_para = []
                merged.append("") # 保持空行
            else:
                current_para.append(stripped)
                
        if current_para:
            merged.append("".join(current_para))
            
        return "\n".join(merged)

    @staticmethod
    def detect_vertical_layout(text: str) -> bool:
        """基于行长统计特征判断是否为竖排"""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            return False
            
        lengths = [len(l) for l in lines]
        avg_length = sum(lengths) / len(lengths)
        
        # 启发式规则：如果平均行长非常短（比如每个字占据一行，或者固定极短字符换行），并且行数较多
        if avg_length < 15 and len(lines) > 20:
            return True
            
        return False

    @staticmethod
    def convert_vertical_pdf_pages(pdf_path: str) -> str:
        """使用 pdfplumber 解析竖排PDF并保持从右到左顺序"""
        import pdfplumber
        all_lines = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                chars = page.chars
                columns = {}
                for c in chars:
                    # 过滤顶部页眉(行号)和底部页脚(页码)
                    if c['top'] < 50 or c['top'] > 500:
                        continue
                    
                    x = c['x0']
                    found_col_x = None
                    for cx in columns.keys():
                        if abs(x - cx) < 8:  # 容差，同一列字符可能有些微x坐标偏移
                            found_col_x = cx
                            break
                    
                    if found_col_x is None:
                        columns[x] = []
                        found_col_x = x
                        
                    columns[found_col_x].append(c)
                
                # 从右到左排序（x坐标从大到小）
                sorted_xs = sorted(columns.keys(), reverse=True)
                
                page_lines = []
                for x in sorted_xs:
                    col_chars = columns[x]
                    # 列内从上到下排序（top坐标从小到大）
                    col_chars.sort(key=lambda item: item['top'])
                    line_text = "".join(c['text'] for c in col_chars)
                    if line_text.strip():
                        page_lines.append(line_text)
                
                all_lines.extend(page_lines)
                
        return "\n".join(all_lines)

    # ===== Stage 2.5: 清理元数据 =====
    @staticmethod
    def filter_script_metadata(text: str) -> str:
        """剥离剧本头部和尾部的非正文内容（如 登场人物、简介、注意事项声明等）"""
        lines = text.splitlines()
        cleaned_lines = []
        
        # 常见元数据行或说明段落的关键字正则（包含各种标记）
        metadata_patterns = [
            r'^トラックNo.*', r'^編集時対応項目.*', r'^セリフ：.*', 
            r'^にて表記しています.*', r'^（以下、台本）.*', r'^・タイトル.*', 
            r'^【\d+[^】]*】.*', r'^＝＝＝+.*', r'^登場人物\s*$', r'^あらすじ\s*$',
            r'^・[^\s]+.*',  # 登场人物列表（可能有空格，所以稍微宽泛）
            r'^.*第[0-9０-９零一二三四五六七八九十百千万]+[話章幕]\s*$', # 标题类
            r'^（第.*話\s*終わり）$'
        ]
        regexes = [re.compile(p) for p in metadata_patterns]
        
        # 状态机：如果匹配到“あらすじ”或“登場人物”，可能要跳过接下来几行
        skip_block = False
        
        # 为了处理“まっしろの部屋で...”等特定标题（如果它紧跟在・タイトル（決定稿）后）
        skip_next_line = False

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
                
            if skip_next_line:
                skip_next_line = False
                continue

            if stripped in ["登場人物", "あらすじ"] or "（以下、台本）" in stripped:
                skip_block = True
                continue
                
            if skip_block:
                # 区块结束条件：遇到＝＝＝＝或者一个长的空行（两行以上空行），但为了简单这里假定＝＝＝或者新段落为主
                if re.match(r'^＝＝＝+.*', stripped):
                    skip_block = False
                    continue
                # 如果是有特征的角色声明如 ・XX
                if stripped.startswith('・'):
                    continue
                # 如果上一行和当前行都不是空，可能依然在あらすじ里
                # 简单起见，如果不符合正则而遇到了明确的开始标志如 `人物:` 或者 `（`，则终止skip
                if re.match(r'^([一-鿿぀-ゟ゠-ヿA-Za-z0-9_-]+)[：:]\s*(.*)$', stripped) or stripped.startswith('（'):
                    skip_block = False
                else:
                    # 对于 あらすじ，很难判定何时结束，只能根据空行。
                    # 如果遇到两个空行以上，跳出。这需要结合上下文。
                    if i > 1 and not lines[i-1].strip() and not lines[i-2].strip():
                        skip_block = False
                    else:
                        continue
            
            # 单行正则过滤
            matched = False
            for rgx in regexes:
                if rgx.search(stripped):
                    matched = True
                    break
            
            if matched:
                if '・タイトル' in stripped:
                    skip_next_line = True
                continue
                
            cleaned_lines.append(line)
            
        # 清除开头和结尾的多余空行
        while cleaned_lines and not cleaned_lines[0].strip():
            cleaned_lines.pop(0)
        while cleaned_lines and not cleaned_lines[-1].strip():
            cleaned_lines.pop()
            
        return "\n".join(cleaned_lines)

    # ===== Stage 3: 台词提取 =====
    @staticmethod
    def extract_dialogue(
        text: str,
        known_characters: List[str] = None,
        options: Dict = None,
    ) -> List[Dict]:
        """提取结构化台词
        Returns: [{
            "character": str | None,
            "lines": List[str],           # 纯台词文本（已去除括号内容）
            "stage_actions": List[str],   # 提取出的括号内容
            "raw_block": str,             # 原始文本块
        }, ...]
        """
        if options is None:
            options = {}
            
        lines = text.splitlines()
        entries = []
        
        char_pattern = re.compile(r'^([一-鿿぀-ゟ゠-ヿA-Za-z0-9_-]+)[：:]\s*(.*)$')
        
        current_char = None
        current_lines = []
        current_raw = []
        current_actions = []
        
        def commit_entry():
            if current_lines or current_raw:
                raw_text = "\n".join(current_raw)
                
                # Further exact actions from current_lines
                merged_line = "\n".join(current_lines)
                clean_text, actions = ScriptProcessor.extract_stage_descriptions(merged_line, mode="remove")
                
                all_actions = current_actions.copy()
                all_actions.extend([a["text"] for a in actions])
                
                entries.append({
                    "character": current_char,
                    "lines": [clean_text] if clean_text else [],
                    "stage_actions": all_actions,
                    "raw_block": raw_text
                })
                
        for line in lines:
            stripped = line.strip()
            if not stripped:
                commit_entry()
                current_char = None
                current_lines = []
                current_raw = []
                current_actions = []
                continue
                
            m = char_pattern.match(stripped)
            if m:
                commit_entry()
                current_char = m.group(1)
                current_raw = [stripped]
                current_actions = []
                
                content = m.group(2).strip()
                if content:
                    # check if pure bracket
                    is_pure_bracket = bool(re.match(r'^[（(［\[〈<].*[)）\]］〉>]$', content))
                    if is_pure_bracket:
                        current_actions.append(content)
                    else:
                        current_lines = [content]
            else:
                current_raw.append(stripped)
                is_pure_bracket = bool(re.match(r'^[（(［\[〈<].*[)）\]］〉>]$', stripped))
                if is_pure_bracket:
                    current_actions.append(stripped)
                else:
                    current_lines.append(stripped)
                    
        commit_entry()
        return entries

    @staticmethod
    def detect_character_names(text: str) -> List[str]:
        """检测剧本中的角色名"""
        chars = set()
        # 找 등장人物 或 登场人物 块
        # 简单回退：正则匹配全部 XXX:
        pattern = re.compile(r'^([\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffA-Za-z0-9_-]+)[：:]\s*.*$')
        for line in text.splitlines():
            m = pattern.match(line.strip())
            if m:
                chars.add(m.group(1))
        return list(chars)

    # ===== Stage 4: 情景描述处理 =====
    @staticmethod
    def extract_stage_descriptions(
        text: str,
        mode: str = "remove",  # remove / filter_extract / keep
    ) -> Tuple[str, List[Dict]]:
        """提取/处理括号中的舞台指示"""
        if mode == "keep":
            return text, []
            
        actions = []
        patterns = {
            "paren": re.compile(r'[（(][^)）]*[)）]'),
            "bracket": re.compile(r'[［\[][^］\]]*[］\]]'),
            "angle": re.compile(r'[〈<][^〉>]*[〉>]'),
        }
        
        result_text = text
        for ptype, pattern in patterns.items():
            for m in pattern.finditer(result_text):
                actions.append({
                    "text": m.group(),
                    "type": ptype
                })
            
            if mode == "remove" or mode == "filter_extract":
                result_text = pattern.sub('', result_text)
                
        # 清理多余空格
        result_text = re.sub(r'[ \t]{2,}', ' ', result_text).strip()
        return result_text, actions

    @staticmethod
    def classify_parenthetical(content: str) -> str:
        """分类括号内容"""
        if '★' in content or '音' in content or 'SE' in content.upper():
            return "sound_effect"
        if content.startswith('（') and content.endswith('）'):
             # 启示性判断：包含动词等，粗略全归为舞台指示
             return "stage_direction"
        return "other"

    # ===== Stage 5: 导出 =====
    @staticmethod
    def to_subtitle_text(
        dialogue_entries: List[Dict],
        include_character: bool = False,
        include_actions: bool = False,
    ) -> str:
        """转换为给 SubtitleGenerator 的纯文本
        去除重复提取动作，直接使用提取好的 lines 和 stage_actions
        """
        out_lines = []
        for entry in dialogue_entries:
            lines_text = "\n".join(entry.get("lines", []))
            actions_text = " ".join(entry.get("stage_actions", []))
            
            if include_actions and actions_text:
                if lines_text:
                    lines_text = f"{actions_text} {lines_text}"
                else:
                    lines_text = actions_text
                    
            if not lines_text.strip():
                if include_actions and entry.get("raw_block"):
                     out_lines.append(entry["raw_block"])
                continue
                
            if include_character and entry.get("character"):
                out_lines.append(f"{entry['character']}：{lines_text}")
                out_lines.append("") # 如果带角色名，不同角色间加空行易读
            else:
                out_lines.append(lines_text)
                
        return "\n".join(out_lines).strip()