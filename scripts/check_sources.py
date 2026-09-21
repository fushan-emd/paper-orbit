import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from literature_radar.http import request
root=Path(__file__).resolve().parents[1];out=root/'release_validation';out.mkdir(exist_ok=True)
targets=[('pubmed','https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',{'db':'pubmed','term':'single cell','retmax':1,'retmode':'json'}),
('arxiv','https://export.arxiv.org/api/query',{'search_query':'all:single_cell','max_results':1}),
('openalex','https://api.openalex.org/works',{'search':'single cell','per-page':1}),
('biorxiv','https://api.biorxiv.org/details/biorxiv/2026-09-19/2026-09-20/0',{})]
results=[]
for name,url,params in targets:
 start=time.monotonic()
 try:
  response=request('GET',url,params=params,timeout=(10,20),retry_total=0)
  valid=('feed' in response.text) if name=='arxiv' else isinstance(response.json(),dict)
  results.append({'source':name,'status':'passed' if valid else 'invalid_response','http_status':response.status_code,'bytes':len(response.content),'seconds':round(time.monotonic()-start,2)})
 except Exception as exc:results.append({'source':name,'status':'failed','error_type':type(exc).__name__,'seconds':round(time.monotonic()-start,2)})
 print(json.dumps(results[-1]),flush=True)
(out/'source-connectivity.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
