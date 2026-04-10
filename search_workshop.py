import ast
import json

with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()
    tree = ast.parse(text)

funcs = []
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
        for n in node.body:
            if isinstance(n, ast.FunctionDef):
                if 'workshop' in n.name or 'voice' in n.name or 'clone' in n.name or 'segment' in n.name or 'design' in n.name or 'template' in n.name:
                    funcs.append(n.name)

print(json.dumps(funcs, indent=2))
