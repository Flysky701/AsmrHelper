import ast
import json

with open('src/gui/workers/pipeline_worker.py', 'r', encoding='utf-8') as f:
    tree = ast.parse(f.read(), filename='pipeline_worker.py')

classes = []
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        classes.append(node.name)
print(json.dumps(classes, indent=2))
