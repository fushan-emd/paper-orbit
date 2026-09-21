"""Check release files and produce a SHA256 manifest. No credentials or live requests."""
from pathlib import Path
import hashlib
import json
root=Path(__file__).resolve().parents[1];dist=root/'dist_release/BioinfoLiteratureRadar';out=root/'release_validation';out.mkdir(exist_ok=True)
files=[p for p in dist.rglob('*') if p.is_file()]
for p in files:
    assert p.suffix.lower() not in {'.sqlite','.db','.bak'},f'Private database/backup in artifact: {p.name}'
    assert p.name.lower() not in {'secrets.json','config.toml.bak'},f'Credential file in artifact: {p.name}'
    if p.name=='config.toml':assert p.relative_to(dist).as_posix()=='_internal/installer/config.toml'
required=['BioinfoLiteratureRadar.exe','_internal/LICENSE','_internal/PRIVACY.md','_internal/installer/config.toml','_internal/literature_radar/assets/library.css','_internal/literature_radar/assets/workbench.js']
assert all((dist/p).is_file() for p in required)
manifest={p.relative_to(dist).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(out/'artifact-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
installer=root/'release/PaperOrbit-0.4.0-beta.2-Setup.exe'
if installer.exists():(installer.with_suffix('.sha256')).write_text(hashlib.sha256(installer.read_bytes()).hexdigest()+'  '+installer.name+'\n',encoding='utf-8')
print(json.dumps({'artifact_files':len(files),'no_database_or_secret_files':True,'installer':installer.exists()}))
