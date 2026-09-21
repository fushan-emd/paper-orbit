"""Run the actual bundled executable against an isolated, empty workspace."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import re
import requests
import tomllib
root=Path(__file__).resolve().parents[1];workspace=root/'release_validation/packaged-workspace';workspace.mkdir(exist_ok=True)
import sys
exe=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'dist_release/BioinfoLiteratureRadar/BioinfoLiteratureRadar.exe'
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
env={**os.environ,'LITERATURE_RADAR_ROOT':str(workspace)}
process=subprocess.Popen([str(exe),'--no-window','--no-browser','--port',str(port)],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
checks=[]
try:
 session=requests.Session();base=f'http://127.0.0.1:{port}'
 for _ in range(100):
  if process.poll() is not None:raise RuntimeError('Bundled executable exited before serving')
  try:
   page=session.get(base+'/',timeout=1)
   if page.status_code==200:break
  except requests.RequestException:pass
  time.sleep(.2)
 else:raise RuntimeError('Bundled app did not start')
 token=re.search(r'name="_csrf" value="([^"]+)"',page.text)[1]
 session.headers['X-Orbit-Token']=token
 for path in ['/discover','/manage','/api/inventory','/api/ideas/history','/policy/privacy','/policy/license','/policy/notices']:
  response=session.get(base+path,timeout=5);assert response.status_code==200,(path,response.status_code);checks.append(path)
 tutorial=session.get(base+'/discover',timeout=5)
 assert 'window.orbitTourState=' in tutorial.text and '/onboarding/progress' in tutorial.text
 checks.append('onboarding_assets')
 saved=tomllib.loads((workspace/'config.toml').read_text(encoding='utf-8'))['web']
 boot=json.loads(re.search(r'window.orbitTourState=(.*?);</script>',tutorial.text)[1])
 assert boot['step']==saved.get('tutorial_step',0)
 response=session.post(base+'/onboarding/progress',data={'step':'4','active':'1'},timeout=5)
 assert response.status_code==200
 saved=tomllib.loads((workspace/'config.toml').read_text(encoding='utf-8'))['web']
 assert saved['tutorial_step']==4 and saved['show_onboarding']
 checks.append('onboarding_persistence')
 response=session.post(base+'/manage/backup',data={},timeout=5);assert response.status_code==200
 assert list((workspace/'backups').glob('*.sqlite'))
 response=session.get(base+'/api/export',timeout=5);assert response.json()['format']=='paper-orbit-library-v1'
 (root/'release_validation/packaged-smoke.json').write_text(json.dumps({'status':'passed','checks':checks+['backup','export'],'isolated_workspace':True,'native_webview_window_tested':False},indent=2),encoding='utf-8')
 print('PASS: packaged executable starts, serves all UI pages, policies, APIs, backup and export.')
finally:
 process.terminate()
 try:process.wait(timeout=10)
 except subprocess.TimeoutExpired:process.kill();process.wait()
