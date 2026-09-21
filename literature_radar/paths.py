"""A single workspace root, independent of bundled resources."""
import os
import shutil
from literature_radar.backup import database_connection
import sys
from pathlib import Path


def resource_root():
    return Path(__file__).resolve().parents[1]


def workspace_root():
    override=os.environ.get('LITERATURE_RADAR_ROOT')
    if override: return Path(override).resolve()
    if getattr(sys,'frozen',False):
        return Path(os.environ.get('LOCALAPPDATA',Path.home())) / 'PaperOrbit'
    return resource_root()


def prepare_workspace():
    root=workspace_root();root.mkdir(parents=True,exist_ok=True)
    for folder in ['data','reports','logs','backups']: (root/folder).mkdir(exist_ok=True)
    target=root/'config.toml'
    if target.exists(): return root
    legacy=Path(sys.executable).parent if getattr(sys,'frozen',False) else resource_root()
    old=legacy/'config.toml'
    default=resource_root()/'installer/config.toml'
    if old.exists() and legacy.resolve()!=root.resolve() and not os.environ.get("LITERATURE_RADAR_ROOT"):
        from literature_radar.config import load_config
        config=load_config(old)
        for key in ['database','report_dir']:
            rel=Path(config['project'][key])
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('Legacy workspace uses external paths. Export and migrate it explicitly before first launch.')
        src=legacy/config['project']['database'];dst=root/config['project']['database']
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True,exist_ok=True)
            with database_connection(src.resolve().as_uri()+'?mode=ro',uri=True) as source, database_connection(dst) as dest:
                source.backup(dest)
        reports=legacy/config['project']['report_dir']
        if reports.exists():shutil.copytree(reports,root/config['project']['report_dir'],dirs_exist_ok=True)
        # Credential migration imports directly from legacy paths, never copies plaintext secrets.
        from literature_radar.secrets import migrate_legacy
        for vault in [legacy/'data/secrets.json',legacy/'_internal/data/secrets.json']:
            migrate_legacy(vault)
        shutil.copy2(old,target)
    else:
        shutil.copy2(default,target)
    return root


_workspace_lock_handle=None

def acquire_workspace_lock():
    global _workspace_lock_handle
    if _workspace_lock_handle:return
    root=workspace_root();root.mkdir(parents=True,exist_ok=True)
    handle=open(root/'.workspace.lock','a+b')
    try:
        if os.name=='nt':
            import msvcrt
            handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close();raise RuntimeError('This Paper Orbit workspace is already open. Close the other instance first.')
    _workspace_lock_handle=handle


def startup_backup():
    from datetime import date
    from literature_radar.config import load_config
    from literature_radar.backup import snapshot
    root=workspace_root();config=load_config(root/'config.toml');db=root/config['project']['database']
    if db.exists() and not list((root/'backups').glob(date.today().strftime('%Y%m%d')+'-*-daily-*.sqlite')):
        snapshot(db,root/'backups','daily')


def migrate_config_credentials():
    from literature_radar.config import load_config,write_config
    from literature_radar.secrets import save_secret,migrate_legacy
    root=workspace_root();migrate_legacy();config=load_config(root/'config.toml')
    key=config.get('sources',{}).get('pubmed',{}).get('api_key')
    if key:
        save_secret('NCBI_API_KEY',key);config['sources']['pubmed']['api_key']='';write_config(config,root/'config.toml')
        # Old config backups may contain this same legacy key: scrub only that field.
        for path in [root/'config.toml.bak',root/'config.toml.writecheck']:
            if path.exists():
                try:
                    import tomllib
                    data=tomllib.loads(path.read_text(encoding='utf-8'));data['sources']['pubmed']['api_key']=''
                    from literature_radar.config import _dump_toml
                    path.write_text(_dump_toml(data),encoding='utf-8')
                except (ValueError,KeyError):pass
