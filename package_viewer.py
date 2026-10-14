"""Build into fresh directories only; never deletes previous packages."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parent

def package(output):
    target=output/'HD2AudioViewer'
    for name in ('theme','vgmstream-win64','ui_assets'):
        shutil.copytree(ROOT/name,target/name)
    for name in ('azure.tcl','friendlynames.db','readonly_defaults.json','LICENSE'):
        shutil.copy2(ROOT/name,target/name)
    shutil.copy2(ROOT/'ui_assets/app.ico',target/'icon.ico')
    shutil.copy2(ROOT/'README_UPDATES_ZH.md',target/'使用说明.md')
    archive=output/'HD2AudioViewer-0.1.0.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as zipped:
        for path in target.rglob('*'):
            if path.is_file():zipped.write(path,path.relative_to(output))
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert 'HD2AudioViewer/audio_modder.exe' in zipped.namelist()
        assert not any('/_internal/' in p for p in zipped.namelist())
    report={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in target.rglob('*') if p.is_file()}
    report[archive.name]=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/'sha256.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('name',help='Fresh build/output suffix')
    parser.add_argument('--resources-only',action='store_true')
    args=parser.parse_args()
    if not args.name.replace('-','').isalnum():parser.error('Use letters, digits and hyphens')
    output=ROOT/('output-'+args.name)
    work=ROOT/('build-'+args.name)
    if not args.resources_only:
        if output.exists() or work.exists():parser.error('Choose a fresh suffix; existing output is preserved')
        subprocess.run([sys.executable,'-m','PyInstaller','--distpath',str(output/'HD2AudioViewer'),
                        '--workpath',str(work),'HD2OriginalLayout.spec'],cwd=ROOT,check=True)
    package(output)
