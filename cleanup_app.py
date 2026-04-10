import ast
import re

with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    src = f.read()

parsed = ast.parse(src)
lines = src.splitlines(keepends=True)
methods_to_remove = ['_browse_clone_audio']

ranges_to_remove = []

for node in parsed.body:
    if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
        for n in node.body:
            if isinstance(n, ast.FunctionDef) and n.name in methods_to_remove:
                start = n.lineno - 1
                end = n.end_lineno
                if n.decorator_list:
                    start = n.decorator_list[0].lineno - 1
                ranges_to_remove.append((start, end))

ranges_to_remove.sort(key=lambda x: x[0], reverse=True)

for start, end in ranges_to_remove:
    del lines[start:end]

with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(''.join(lines))
print("Removed orphaned methods")
