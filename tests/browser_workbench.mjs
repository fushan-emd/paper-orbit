// Browser smoke checks using Node 22+ and a locally installed Edge/Chrome; no npm dependencies.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';

const [baseUrl, browserPath, outputDir] = process.argv.slice(2);
const profile = await mkdtemp(path.join(tmpdir(), 'radar-browser-test-'));
const browser = spawn(browserPath, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile,
  'about:blank'], {windowsHide: true, stdio: 'ignore'});
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
let sequence = 0;
const pending = new Map();
const exceptions = [];
async function until(check, message) {
  for (let i = 0; i < 100; i++) {
    if (await check()) return;
    await pause(100);
  }
  throw new Error(message);
}
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 10000);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function captureLight(name,selector,maxHeight=900){
  await evaluate("applyTheme('light')");
  await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const clip=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:Math.min(r.height,${maxHeight}),scale:1}})()`);
  const capture=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
  await writeFile(path.join(outputDir,name),Buffer.from(capture.data,'base64'));
}
async function navigate(url) {
  await command('Page.navigate', {url});
  await until(() => evaluate("document.readyState === 'complete' && !!document.querySelector('.draw-console')"), 'Page did not load');
}
try {
  let port;
  await until(async () => {
    try { port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; return !!port; }
    catch { return false; }
  }, 'Browser did not start');
  const pages = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  socket = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params);
    const request = pending.get(message.id);
    if (request) {
      clearTimeout(request.timer);
      pending.delete(message.id);
      if (message.error) request.reject(new Error(JSON.stringify(message.error)));
      else request.resolve(message.result);
    }
  };
  await command('Runtime.enable');
  await command('Page.enable');
  await command('Emulation.setDeviceMetricsOverride', {width: 1360, height: 1000, deviceScaleFactor: 1, mobile: false});
  await navigate(baseUrl+'discover');
  await until(()=>evaluate('flow.checked && state.summary !== null'),'Collection state did not load');
  assert.equal(await evaluate('flow.ready'),false);
  assert.equal(await evaluate('state.summary.remaining'),0);
  assert.equal(await evaluate("document.querySelector('[data-count=\"10\"]').disabled"),false);
  await evaluate("document.querySelector('[data-count=\"10\"]').click()");
  await until(()=>evaluate('flow.ready && !flow.collecting && !state.busy && state.cards.length===10'),'First draw did not collect then draw');
  assert.equal(await evaluate('flow.collectionJob.result.added'),30);
  const collectionId=await evaluate('flow.collectionJob.id');
  for(let i=0;i<2;i++){
    const previous=await evaluate('state.batch.id');
    await evaluate("document.querySelector('[data-count=\"10\"]').click()");
    await until(()=>evaluate('!state.busy && state.batch.id !== '+JSON.stringify(previous)),'Next draw failed');
  }
  assert.equal(await evaluate('flow.collectionJob.id'),collectionId);
  await evaluate("location.hash='warehouse'");
  await until(()=>evaluate("flow.view==='warehouse' && flow.owned.total===30"),'Cards were not stored in warehouse');
  assert.equal(await evaluate("document.querySelectorAll('#warehouse-grid .owned-card').length"),20);
  await evaluate("document.querySelector('#warehouse-grid [data-select]').click()");
  assert.equal(await evaluate('flow.selected.size'),1);
  await evaluate("document.querySelector('#warehouse-grid [data-action=favorite]').click()");
  await until(()=>evaluate('state.pending.size===0 && flow.owned.cards[0].favorite'),'Warehouse favorite failed');
  await evaluate("document.getElementById('warehouse-next').click()");
  await until(()=>evaluate('flow.owned.page===2'),'Warehouse pagination failed');
  await evaluate("document.querySelector('#warehouse-grid [data-select]').click()");
  assert.equal(await evaluate('flow.selected.size'),2);
  await until(()=>evaluate("document.querySelectorAll('#warehouse-grid .owned-card').length===10 && [...document.querySelectorAll('#warehouse-grid .owned-card')].every(c=>Number(getComputedStyle(c).opacity)===1)"),'Warehouse cards were not fully visible');
  await evaluate("applyTheme('dark');window.scrollTo(0,0)");
  await evaluate('Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))');
  let shot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'warehouse-desktop.png'),Buffer.from(shot.data,'base64'));
  await captureLight('warehouse-light.png','#warehouse-view',850);
  await captureLight('selection-light.png','#warehouse-grid',570);
  await evaluate("applyTheme('dark')");
  await evaluate("location.hash='lab'");
  await until(()=>evaluate("flow.view==='lab'"),'Idea lab did not open');
  await evaluate("document.getElementById('research-question').value='只使用公开数据，先验证跨组织迁移；这是测试任务。';document.getElementById('research-question').dispatchEvent(new Event('input',{bubbles:true}));");
  await evaluate(`window.originalFetch=window.fetch;window.lostIdea=false;
    window.fetch=async(...args)=>{const response=await originalFetch(...args);if(String(args[0])==='/api/ideas'&&!lostIdea){lostIdea=true;await response.text();throw new Error('Simulated lost AI response');}return response;};
    document.getElementById('generate-ideas').click();`);
  await until(()=>evaluate('lostIdea && !flow.ideaRunning'),'Lost generation response did not settle');
  await evaluate("window.fetch=originalFetch;document.getElementById('generate-ideas').click()");
  await until(()=>evaluate("!flow.ideaRunning && flow.activeResult?.status==='succeeded'"),'Idea recovery failed');
  assert.equal(await evaluate('flow.activeResult.result.sources.length'),2);
  assert.equal(await evaluate("document.querySelectorAll('#idea-result .source-evidence').length"),2);
  assert.equal(await evaluate('flow.activeResult.result.novelty_verified'),false);
  assert.equal(await evaluate("document.querySelectorAll('#idea-result script,#idea-result img').length"),0);
  await evaluate("showIdeaFailure({status:'failed',result:{error_code:'output_truncated'}})");
  assert.equal(await evaluate("document.getElementById('generation-state').textContent.includes(T.error_output_truncated)"),true);
  assert.equal(await evaluate('flow.selected.size'),2);
  await evaluate("showIdeaFailure({status:'failed',result:{},error:'Task failed (JSONDecodeError).'})");
  assert.equal(await evaluate("document.getElementById('generation-state').textContent.includes(T.error_invalid_json)"),true);
  const ideaId=await evaluate('flow.activeResult.id');
  await evaluate('window.beforeReloadMarker=true');
  await command('Page.reload',{ignoreCache:true});
  await until(()=>evaluate("!window.beforeReloadMarker && typeof flow!=='undefined' && flow.selected.size===2 && flow.activeResult!==null").catch(()=>false),'Draft or idea archive was not restored after a full reload');
  assert.equal(await evaluate('flow.activeResult.id'),ideaId);
  assert.equal(await evaluate("document.getElementById('research-question').value.includes('公开数据')"),true);
  await evaluate('window.scrollTo(0,0)');
  await evaluate('Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))');
  const metrics=await command('Page.getLayoutMetrics');
  shot=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:1360,height:Math.min(1800,metrics.cssContentSize.height),scale:1}});
  await writeFile(path.join(outputDir,'idea-lab-desktop.png'),Buffer.from(shot.data,'base64'));
  await captureLight('idea-lab-light.png','#lab-view',1500);
  await captureLight('composer-light.png','.lab-composer',700);
  await captureLight('evidence-light.png','#idea-result',800);
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await evaluate("applyTheme('light');window.scrollTo(0,0)");
  await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  await evaluate('Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))');
  assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
  shot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'idea-lab-mobile.png'),Buffer.from(shot.data,'base64'));
  await evaluate("location.hash='discover'");
  await until(()=>evaluate("flow.view==='discover'"),'Discover tab failed');
  await evaluate("document.getElementById('reset-round').click()");
  await until(()=>evaluate('!state.busy&&state.summary.remaining===30'),'Reset failed');
  await evaluate("location.hash='warehouse'");
  await until(()=>evaluate("flow.view==='warehouse'&&flow.owned.total===30"),'Reset erased owned cards');
  assert.equal(exceptions.length,0,JSON.stringify(exceptions));
  console.log('PASS: pre-draw collection, daily reuse, permanent warehouse, cross-page combo, favorites, lost AI response recovery, source-linked hypotheses, persistent draft/history, mobile layout.');
} catch (error) {
  console.error(error.stack || error);
  process.exitCode = 1;
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    await command('Browser.close').catch(() => {});
    socket.close();
  }
  if (browser.exitCode === null) await Promise.race([new Promise(resolve => browser.once('exit', resolve)), pause(3000)]);
  if (browser.exitCode === null) browser.kill();
  const resolved = path.resolve(profile);
  if (path.dirname(resolved) === path.resolve(tmpdir()) && path.basename(resolved).startsWith('radar-browser-test-')) {
    await rm(resolved, {recursive: true, force: true, maxRetries: 10, retryDelay: 200});
  }
}