"""Durable background tasks with leases, idempotent starts and progress reporting."""
from __future__ import annotations
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from literature_radar.collector import collect_library
from literature_radar.ideation import IdeaGenerationError
from requests.exceptions import HTTPError, Timeout, ConnectionError
from literature_radar.usage import BudgetExceeded


class TaskCancelled(Exception):pass


class JobBusyError(ValueError):
    pass


class TaskStore:
    def __init__(self, store):
        self.store=store
        with store._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS workflow_jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                options_json TEXT NOT NULL, result_json TEXT, error TEXT NOT NULL DEFAULT '',
                log_json TEXT NOT NULL DEFAULT '[]', started REAL NOT NULL,
                heartbeat REAL NOT NULL, finished REAL)''')
            columns={row['name'] for row in conn.execute('PRAGMA table_info(workflow_jobs)')}
            if 'cancel_requested' not in columns:conn.execute('ALTER TABLE workflow_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0')
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_active ON workflow_jobs(kind) WHERE status='running'")

    def recover(self):
        with self.store._connect() as conn:
            conn.execute("""UPDATE workflow_jobs SET status='interrupted',error='Task interrupted; please retry.',finished=?
                            WHERE status='running' AND heartbeat < ?""",(time.time(),time.time()-45))

    @staticmethod
    def unpack(row):
        if row is None:return None
        result=dict(row)
        for key in ['options','result','log']:
            result[key]=json.loads(result.pop(key+'_json') or ('[]' if key=='log' else '{}'))
        return result

    def get(self,job_id):
        self.recover()
        with self.store._connect() as conn:
            row=conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(job_id,)).fetchone()
        if row is None:raise LookupError('Task not found')
        return self.unpack(row)

    def latest(self,kind):
        self.recover()
        with self.store._connect() as conn:
            return self.unpack(conn.execute('SELECT * FROM workflow_jobs WHERE kind=? ORDER BY started DESC LIMIT 1',(kind,)).fetchone())

    def history(self,kind,limit=30):
        self.recover()
        with self.store._connect() as conn:
            return [self.unpack(r) for r in conn.execute('SELECT * FROM workflow_jobs WHERE kind=? ORDER BY started DESC LIMIT ?', (kind,limit))]

    def log(self,job_id,message):
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT log_json FROM workflow_jobs WHERE id=?',(job_id,)).fetchone()
            lines=json.loads(row[0]);lines.append(str(message))
            conn.execute("UPDATE workflow_jobs SET log_json=?,heartbeat=? WHERE id=? AND status='running'",
                         (json.dumps(lines[-60:],ensure_ascii=False),time.time(),job_id))

    def start(self,kind,options,worker,request_id=None,attach=False):
        job_id=str(uuid.UUID(request_id)) if request_id else str(uuid.uuid4())
        self.recover()
        encoded=json.dumps(options,sort_keys=True,ensure_ascii=False)
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(job_id,)).fetchone()
            if old:
                if old['kind']!=kind or old['options_json']!=encoded:raise ValueError('Request ID reused with different options')
                return self.unpack(old)
            active=conn.execute("SELECT * FROM workflow_jobs WHERE kind=? AND status='running'",(kind,)).fetchone()
            if active:
                if attach:return self.unpack(active)
                raise JobBusyError('Another generation is running. Wait for it to finish.')
            now=time.time()
            conn.execute('INSERT INTO workflow_jobs(id,kind,status,options_json,started,heartbeat) VALUES (?,?,?,?,?,?)',
                         (job_id,kind,'running',encoded,now,now))
        threading.Thread(target=self._work,args=(job_id,worker),daemon=True).start()
        return self.get(job_id)

    def cancel(self,job_id):
        with self.store._connect() as conn:
            conn.execute("UPDATE workflow_jobs SET cancel_requested=1 WHERE id=? AND status='running'",(job_id,))
        return self.get(job_id)

    def _work(self,job_id,worker):
        stop=threading.Event()
        def heartbeat():
            while not stop.wait(5):
                try:
                    with self.store._connect() as conn:
                        conn.execute("UPDATE workflow_jobs SET heartbeat=? WHERE id=? AND status='running'",(time.time(),job_id))
                except Exception:pass
        pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
        try:
            def emit(message):
                if self.get(job_id)['cancel_requested']:raise TaskCancelled()
                self.log(job_id,message)
            emit('Task started.')
            result=worker(emit)
            if self.get(job_id)['cancel_requested']:raise TaskCancelled()
            status='partial' if result.get('sources_failed') else 'succeeded'
            error=''
        except Exception as exc:
            result={};status='failed'
            # Never persist raw HTTP errors, credentials or request bodies.
            error='Task failed ('+type(exc).__name__+'). Check configuration, evidence or network and retry.'
            if isinstance(exc,TaskCancelled):status='cancelled';result={'error_code':'cancelled'}
            elif isinstance(exc,BudgetExceeded):result={'error_code':'budget_limit'}
            elif isinstance(exc, IdeaGenerationError): result={'error_code':exc.code}
            elif isinstance(exc, Timeout): result={'error_code':'timeout'}
            elif isinstance(exc, ConnectionError): result={'error_code':'connection'}
            elif isinstance(exc, HTTPError):
                status=exc.response.status_code if exc.response is not None else None
                result={'error_code':{401:'authentication',403:'authentication',402:'balance',404:'model_unavailable',429:'rate_limit'}.get(status,'provider_error')}
            elif isinstance(exc, json.JSONDecodeError): result={'error_code':'invalid_json'}
        finally:
            stop.set();pulse.join(timeout=6)
        with self.store._connect() as conn:
            conn.execute("""UPDATE workflow_jobs SET status=?,result_json=?,error=?,heartbeat=?,finished=?
                            WHERE id=? AND status='running'""",
                         (status,json.dumps(result,ensure_ascii=False),error,time.time(),time.time(),job_id))


def collection_fingerprint(config):
    selected={key:config.get(key,{}) for key in ['run','sources','profile','weights','analysis']}
    return hashlib.sha256(json.dumps(selected,sort_keys=True,default=str).encode()).hexdigest()


def collection_state(tasks,config):
    job=tasks.latest('collection')
    fresh=bool(job and job['status'] in {'succeeded','partial'} and
               datetime.fromtimestamp(job['finished']).date()==datetime.now().date() and
               job['options'].get('fingerprint')==collection_fingerprint(config))
    return {'fresh':fresh,'job':job}


def ensure_collection(tasks,config,root: Path,force=False,request_id=None):
    state=collection_state(tasks,config)
    if state['fresh'] and not force:return state
    job=tasks.start('collection',{'fingerprint':collection_fingerprint(config)},
                    lambda emit:collect_library(config,root,emit),request_id=request_id,attach=True)
    if job['status']!='running':return collection_state(tasks,config)
    return {'fresh':False,'job':job}