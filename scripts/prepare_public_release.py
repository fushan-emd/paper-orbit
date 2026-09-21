"""Allowlist-only source export. Never copy a working directory wholesale."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import tomllib

ROOT_FILES = {
    '.gitignore', '.gitattributes', 'LICENSE', 'README.md', 'README.en.md', 'DESKTOP_APP.md', 'PUBLIC_RELEASE.md',
    'PRIVACY.md', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md',
    'desktop_app.py', 'web_app.py', 'main.py', 'BioinfoLiteratureRadar.spec',
    'requirements.txt', 'requirements-runtime.lock', 'requirements-build.lock',
    'start_desktop_app.bat', 'start_desktop_app.vbs',
}
SCRIPT_FILES = {
    'build_desktop_app.ps1', 'run_daily.ps1', 'run_web.ps1', 'start_desktop_app.ps1',
    'start_clean_workspace.ps1', 'prepare_public_release.py', 'render_readme.mjs', 'check_sources.py',
    'validate_release.py', 'verify_artifact.py', 'smoke_packaged.py', 'test_installer.ps1',
}
PATTERNS = [
    ('private_key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('api_token', re.compile(r'\b(?:sk-[A-Za-z0-9_-]{24,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b')),
    ('local_author_path', re.compile(r'(?:[A-Z]:[\\/]Users[\\/](?!Public\b|Default\b)[^\s\\/"\']+|E:[\\/]github[\\/]project)', re.I)),
]

def allowed(rel):
    name=rel.as_posix()
    if name in ROOT_FILES or name == 'PUBLIC_MANIFEST.json': return True
    if name in {'docs/images/overview.png','docs/images/cards.png','docs/images/warehouse.png','docs/images/settings.png','docs/images/hero-zh.png','docs/images/hero-en.png','docs/images/idea-lab.png'}: return True
    parts=rel.parts
    if '__pycache__' in parts or any(x.startswith('.') for x in parts): return False
    if name in {'installer/config.toml','installer/BioinfoLiteratureRadar.iss'}: return True
    if len(parts)==2 and parts[0]=='scripts': return parts[1] in SCRIPT_FILES
    if len(parts)==2 and parts[0]=='tests': return rel.suffix in {'.py','.mjs'}
    if len(parts)==2 and parts[0]=='literature_radar': return rel.suffix=='.py'
    if len(parts)==3 and parts[:2]==('literature_radar','fetchers'): return rel.suffix=='.py'
    if len(parts)==3 and parts[:2]==('literature_radar','assets'): return rel.suffix in {'.js','.css','.html'}
    if parts[0]=='third_party_licenses': return rel.suffix.lower() in {'','.txt','.md','.rst','.license'}
    return False

def inspect(path,rel):
    if path.is_symlink() or any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [path,*path.parents]):
        raise ValueError('Links not allowed: '+str(rel))
    if not allowed(rel): raise ValueError('Unexpected public file: '+str(rel))
    if rel.suffix=='.png':
        data=path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>10*1024*1024: raise ValueError('Invalid documentation image: '+str(rel))
        return
    text=path.read_text(encoding='utf-8',errors='replace')
    for kind,pattern in PATTERNS:
        if pattern.search(text): raise ValueError(kind+' in '+str(rel)+' (value redacted)')
    if rel.as_posix()=='installer/config.toml':
        config=tomllib.loads(text)
        for source in config['sources'].values():
            for key in ['api_key','email','mailto']:
                if source.get(key): raise ValueError('Default template contains personal source field: '+key)
        for key,value in config['analysis']['deepseek'].items():
            if key in {'api_key','token','password'} and value:raise ValueError('Default AI secret is not empty')

def audit(root):
    files=[]
    for path in root.rglob('*'):
        rel=path.relative_to(root)
        if '.git' in rel.parts:continue
        if path.is_file():inspect(path,rel);files.append(path)
    if not files:raise ValueError('Empty public source')
    for name in ROOT_FILES|{'installer/config.toml','literature_radar/assets/navigation.css'}:
        if not (root/name).is_file():raise ValueError('Required source missing: '+name)
    manifest=root/'PUBLIC_MANIFEST.json'
    if manifest.exists():
        expected=json.loads(manifest.read_text(encoding='utf-8'))['sha256']
        actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p!=manifest}
        if actual!=expected:raise ValueError('Manifest mismatch; regenerate the public snapshot after source changes')
    return files

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',type=Path,help='Check an existing clean snapshot without changing it')
    args=parser.parse_args()
    if args.check:
        files=audit(args.check.resolve());print(json.dumps({'status':'passed','files':len(files)}));return
    source=Path(__file__).resolve().parents[1]
    destination=source/'public-release'/('PaperOrbit-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    selected=[source/name for name in sorted(ROOT_FILES)]
    for folder in ['literature_radar','installer','scripts','tests','third_party_licenses','docs']:
        selected.extend(p for p in (source/folder).rglob('*') if p.is_file() and allowed(p.relative_to(source)))
    # Inspect every selected original before creating an export. Private trees are never traversed.
    for path in selected:inspect(path,path.relative_to(source))
    destination.mkdir(parents=True,exist_ok=False)
    for path in selected:
        rel=path.relative_to(source);target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
        if rel.suffix=='.png':shutil.copyfile(path,target)
        elif rel.suffix=='.md' and rel.parts[0]!='third_party_licenses':
            target.write_text(path.read_text(encoding='utf-8').replace('RELEASE_REVIEW.md','PUBLIC_RELEASE.md'),encoding='utf-8',newline='\n')
        else:target.write_text(path.read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
    files=audit(destination)
    manifest={'format':'paper-orbit-public-source-v1','sha256':{p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    (destination/'PUBLIC_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    audit(destination)
    print(json.dumps({'status':'prepared','path':str(destination),'files':len(files)+1,'private_data_copied':False},ensure_ascii=False))

if __name__=='__main__':main()
