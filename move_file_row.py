import ast
with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()

tree = ast.parse(text)
func_code = None
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
        for n in node.body:
            if isinstance(n, ast.FunctionDef) and n.name == '_make_file_input_row':
                func_code = ast.get_source_segment(text, n)
                break

if func_code:
    indented = '\n'.join('    ' + line if line else '' for line in func_code.split('\n'))
    with open('src/gui/views/tools_tab.py', 'a', encoding='utf-8') as f:
        f.write('\n' + indented)
    # Removing from app.py to fully extract it
    text = text.replace(func_code, '')
    # Check if other tabs use _make_file_input_row
    with open('src/gui/app.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Moved _make_file_input_row")
