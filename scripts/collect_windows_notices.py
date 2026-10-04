"""Collect local dependency notices without fetching or copying personal data."""
from pathlib import Path
import json
import shutil
import tomllib

def collect(root: Path, output: Path):
    records=[]
    lock=tomllib.loads((root/'desktop/src-tauri/Cargo.lock').read_text(encoding='utf-8'))
    registries=list((Path.home()/'.cargo/registry/src').glob('*'))
    for package in lock['package']:
        if not package.get('source','').startswith('registry+'): continue
        folder=next((r/f"{package['name']}-{package['version']}" for r in registries if (r/f"{package['name']}-{package['version']}").is_dir()),None)
        if folder is None: continue
        meta=tomllib.loads((folder/'Cargo.toml').read_text(encoding='utf-8'))['package']
        name=f"{package['name']}-{package['version']}"
        records.append({'ecosystem':'Rust','name':package['name'],'version':package['version'],'license':meta.get('license',''),'repository':meta.get('repository','')})
        for source in folder.iterdir():
            if source.is_file() and source.name.lower().startswith(('license','copying','notice','copyright')):
                target=output/'rust'/name/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    lock=json.loads((root/'desktop/package-lock.json').read_text(encoding='utf-8'))
    for name,package in lock['packages'].items():
        if not name or package.get('dev'):continue
        folder=root/'desktop'/name
        if not (folder/'package.json').exists():continue
        meta=json.loads((folder/'package.json').read_text(encoding='utf-8'))
        records.append({'ecosystem':'npm','name':meta.get('name',name),'version':meta.get('version',''),'license':meta.get('license','')})
        for source in folder.iterdir():
            if source.is_file() and source.name.lower().startswith(('license','copying','notice','copyright')):
                target=output/'npm'/name.removeprefix('node_modules/')/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    output.mkdir(parents=True,exist_ok=True)
    (output/'desktop-dependencies.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (output/'THIRD-PARTY-NOTICES.txt').write_text('ASMR Helper Test 0.2.1-beta.4\nApplication metadata declares MIT.\nThis distribution contains separately licensed third-party software.\nFFmpeg 8.1.2 from Gyan is GPL v3; see ../ffmpeg/LICENSE and ../ffmpeg/README.txt for its build and source information.\nPython, uv, Python packages, native components, Rust crates and npm production dependencies retain notices in this directory and their original package directories.\nModel weights are not bundled and have separate download/license terms.\nThis inventory is not a legal certification.\n',encoding='utf-8')
    return len(records)

if __name__=='__main__':
    import sys
    print(collect(Path(__file__).resolve().parents[1],Path(sys.argv[1])))
