"""Auditable call limits; one transport attempt per model request."""
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from literature_radar.http import request
from literature_radar.security import validate_ai_url

class BudgetExceeded(ValueError):pass

def _connect(config):
    root=config.get('_workspace_root')
    if not root:return None
    path=Path(root)/'data/ai-usage.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path,timeout=15)
    conn.execute("CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,day TEXT,kind TEXT,model TEXT,status TEXT,started REAL,seconds REAL,input_tokens INTEGER,output_tokens INTEGER,limit_tokens INTEGER)")
    return conn

def ai_request(config,kind,url,**kwargs):
    validate_ai_url(url)
    conn=_connect(config);call_id=None;started=time.monotonic()
    if conn:
        try:
            day=datetime.now().date().isoformat();limits=config.get('budget',{})
            conn.execute('BEGIN IMMEDIATE')
            count=conn.execute('SELECT COUNT(*) FROM calls WHERE day=?',(day,)).fetchone()[0]
            if count>=int(limits.get('daily_call_limit',100)):raise BudgetExceeded('Daily AI call limit reached')
            used=conn.execute("SELECT COALESCE(SUM(CASE WHEN status='succeeded' THEN input_tokens+output_tokens ELSE limit_tokens END),0) FROM calls WHERE day=?",(day,)).fetchone()[0]
            payload=kwargs.get('json',{})
            # Reserve a conservative input-byte count plus the declared output limit.
            reserve=len(json.dumps(payload.get('messages',[]),ensure_ascii=False).encode('utf-8'))+int(payload.get('max_tokens',8192))
            if used+reserve>int(limits.get('daily_token_limit',500000)):raise BudgetExceeded('Daily AI token budget reached')
            call_id=conn.execute('INSERT INTO calls(day,kind,model,status,started,limit_tokens) VALUES (?,?,?,?,?,?)',(day,kind,payload.get('model',''),'running',time.time(),reserve)).lastrowid
            conn.commit()
        except Exception:conn.close();raise
    status='failed';input_tokens=output_tokens=None
    try:
        response=request('POST',url,retry_total=0,**kwargs)
        try:
            usage=response.json().get('usage',{})
            input_tokens=int(usage['prompt_tokens']);output_tokens=int(usage['completion_tokens'])
            if input_tokens<0 or output_tokens<0:raise ValueError()
            status='succeeded'
        except (ValueError,KeyError,TypeError,AttributeError):status='usage_unknown'
        return response
    finally:
        if conn:
            conn.execute('UPDATE calls SET status=?,seconds=?,input_tokens=?,output_tokens=? WHERE id=?',(status,time.monotonic()-started,input_tokens,output_tokens,call_id));conn.commit();conn.close()

def usage_summary(config):
    conn=_connect(config)
    if not conn:return []
    try:
        return [dict(zip(['day','calls','input_tokens','output_tokens','uncertain_calls'],row)) for row in conn.execute("SELECT day,COUNT(*),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),SUM(status!='succeeded') FROM calls GROUP BY day ORDER BY day DESC LIMIT 14")]
    finally:conn.close()
