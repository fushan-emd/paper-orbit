"""Consistent SQLite snapshots and validated, rollback-protected restore."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from contextlib import contextmanager

@contextmanager
def database_connection(*args,**kwargs):
    conn=sqlite3.connect(*args,**kwargs)
    try:
        with conn:yield conn
    finally:conn.close()


WORKSPACE_LOCK=threading.RLock()
SCHEMA_VERSION=1


def snapshot(database, directory, label='manual'):
    database=Path(database);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if not database.exists():raise ValueError('No database to back up')
    name=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+label+'-'+uuid.uuid4().hex[:8]+'.sqlite'
    target=directory/name;temp=directory/(name+'.partial')
    try:
        with database_connection(database.resolve().as_uri()+'?mode=ro',uri=True) as source, database_connection(temp) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed')
        temp.replace(target)
    finally:
        if temp.exists():temp.unlink()
    return target


def list_backups(directory):
    return [dict(name=p.name,bytes=p.stat().st_size) for p in sorted(Path(directory).glob('*.sqlite'),reverse=True)]


def validate_backup(path):
    with database_connection(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup is damaged')
        version=conn.execute('PRAGMA user_version').fetchone()[0]
        if version>SCHEMA_VERSION:raise ValueError('Backup was made by a newer application')
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'papers' not in tables:raise ValueError('This is not a Paper Orbit backup')
        columns={r[1] for r in conn.execute('PRAGMA table_info(papers)')}
        if not {'id','title','source','external_id','analysis_json','favorite','read_status','user_note'}.issubset(columns):
            raise ValueError('Backup schema is unsupported')
        if conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]:
            raise ValueError('Unexpected executable schema in backup')


def restore(database,directory,name):
    directory=Path(directory).resolve()
    if Path(name).name!=name or not name.endswith('.sqlite'):raise ValueError('Invalid backup name')
    source=(directory/name).resolve()
    if source.parent!=directory or not source.is_file():raise ValueError('Backup does not exist')
    validate_backup(source)
    with WORKSPACE_LOCK:
        with database_connection(database) as live:
            tables={r[0] for r in live.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'workflow_jobs' in tables and live.execute("SELECT COUNT(*) FROM workflow_jobs WHERE status='running'").fetchone()[0]:
                raise ValueError('Wait for running tasks to finish before restoring')
        previous=snapshot(database,directory,'before-restore')
        try:
            with database_connection(source.resolve().as_uri()+'?mode=ro',uri=True) as src,database_connection(database) as dst:
                src.backup(dst)
                tables={r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'workflow_jobs' in tables:
                    dst.execute("UPDATE workflow_jobs SET status='interrupted',error='Restored from backup; retry interrupted task.' WHERE status='running'")
        except Exception:
            with database_connection(previous) as src,database_connection(database) as dst:src.backup(dst)
            raise
    return previous.name


def export_library(store):
    with store._connect() as conn:
        papers=[dict(row) for row in conn.execute('SELECT * FROM papers ORDER BY id')]
    return {'format':'paper-orbit-library-v1','exported_at':datetime.now().isoformat(),'includes_private_notes':True,'papers':papers}
