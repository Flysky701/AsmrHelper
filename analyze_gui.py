import ast
import json

with open('src/gui.py', 'r', encoding='utf-8') as f:
    tree = ast.parse(f.read(), filename='src/gui.py')

methods = []
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
        for n in node.body:
            if isinstance(n, ast.FunctionDef):
                methods.append(n.name)

print(json.dumps(methods, indent=2))
