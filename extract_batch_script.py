import ast
import sys

def get_class_methods(filepath, cls_name):
    with open(filepath, 'r', encoding='utf-8') as f:
        src = f.read()
    
    parsed = ast.parse(src)
    methods = []
    lines = src.splitlines(keepends=True)
    
    for node in parsed.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for n in node.body:
                if isinstance(n, ast.FunctionDef):
                    start = n.lineno - 1
                    end = n.end_lineno
                    # Decorators
                    if n.decorator_list:
                        start = n.decorator_list[0].lineno - 1
                        
                    methods.append({
                        'name': n.name,
                        'code': ''.join(lines[start:end]),
                        'start': start,
                        'end': end
                    })
    return methods

methods = get_class_methods('src/gui/app.py', 'MainWindow')
batch_methods = ['create_batch_tab', 'browse_batch_dir', 'browse_batch_output', 'refresh_batch_files', 'on_batch_engine_changed', 'get_batch_params', 'start_batch', 'stop_batch', 'on_batch_file_progress', 'on_batch_finished']

batch_code = []
for m in methods:
    if m['name'] in batch_methods:
        batch_code.append(m['code'])

with open('extract_batch_tmp.py', 'w', encoding='utf-8') as f:
    f.writelines(batch_code)
print("Extracted to extract_batch_tmp.py")
