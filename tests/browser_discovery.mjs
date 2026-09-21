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
  await navigate(baseUrl + 'discover');
  const tourStep=()=>evaluate("document.querySelector('#orbit-tour')?.dataset.step");
  async function waitStep(n){await until(async()=>await tourStep()===String(n),'Tour step '+n+' missing');}
  async function advance(n){await evaluate("document.querySelector('#tour-next').click()");await waitStep(n);}
  await waitStep(0);
  assert.equal(await evaluate("document.querySelectorAll('.orbit-global-nav a').length"),5);
  await advance(1);
  assert.equal(await evaluate('location.search'),'?settings=1');
  assert.equal(await evaluate("document.querySelectorAll('.setting-advanced[open]').length"),0);
  assert.equal(await evaluate("document.querySelectorAll('.setting-card').length"),3);
  const preservedQuery=await evaluate("document.querySelector('[name=pubmed_query]').value");
  await evaluate("document.querySelector('#tour-collapse').click()");
  let settingsShot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'settings-simple-desktop.png'),Buffer.from(settingsShot.data,'base64'));
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
  settingsShot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'settings-simple-mobile.png'),Buffer.from(settingsShot.data,'base64'));
  await command('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
  await evaluate("document.querySelector('#tour-collapse').click()");

  await evaluate("document.querySelector('#settings-panel form button[type=submit]').click()");
  await pause(1000);
  if(!await evaluate("!!document.querySelector('#tour-next')"))throw new Error('Settings save: '+await evaluate("location.href+' '+document.body.innerText.slice(0,500)"));
  await waitStep(1);
  assert.equal(await evaluate("document.querySelector('[name=pubmed_query]').value"),preservedQuery);
  await advance(2); await advance(3); await advance(4); await advance(5); await advance(6); await advance(7);
  assert.equal(await evaluate("document.querySelector('.orbit-global-nav [aria-current=page]').dataset.nav"),'manage');
  assert.equal(await evaluate("document.querySelectorAll('.orbit-global-nav a').length"),5);
  await evaluate("document.querySelector('form[action=\"/manage/backup\"] button').click()");
  await pause(500);await waitStep(7);
  await evaluate("document.querySelector('#tour-back').click()");await waitStep(6);
  await evaluate('window.tourReloadMarker=true');
  await command('Page.reload');
  await until(()=>evaluate("window.tourReloadMarker!==true && document.readyState==='complete' && !!document.querySelector('#tour-next')"),'Reload did not finish');
  await waitStep(6);
  await advance(7);
  await evaluate("document.querySelector('#tour-next').click()");
  await until(()=>evaluate("document.querySelector('#orbit-tour').hidden"),'Tour finish failed');
  await navigate(baseUrl+'discover');
  assert.equal(await evaluate("document.querySelector('#orbit-tour').hidden"),true);
  await evaluate("document.querySelector('#open-tutorial').click()");await waitStep(0);
  await evaluate("window.tutorialFetch=window.fetch;window.fetch=async()=>({ok:false});document.querySelector('#tour-next').click()");
  await until(()=>evaluate("!document.querySelector('#tour-error').hidden"),'Tour save error hidden');
  assert.equal(await tourStep(),'0');
  await evaluate("window.fetch=window.tutorialFetch");
  // Taking a normal link keeps the guide active on its destination.
  await evaluate("document.querySelector('a[href=\"/?settings=1\"]').click()");await waitStep(1);
  await advance(2);
  let welcomeShot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'onboarding-desktop.png'),Buffer.from(welcomeShot.data,'base64'));
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate("document.querySelector('#orbit-tour').scrollWidth <= document.querySelector('#orbit-tour').clientWidth"),true);
  welcomeShot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'onboarding-mobile.png'),Buffer.from(welcomeShot.data,'base64'));
  await evaluate("document.querySelector('#tour-collapse').click()");
  assert.equal(await evaluate("document.querySelector('#tour-body').hidden"),true);
  await evaluate("document.querySelector('#tour-collapse').click();document.querySelector('#tour-skip').click()");
  await until(()=>evaluate("document.querySelector('#orbit-tour').hidden"),'Tour skip failed');
  await command('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
  await until(() => evaluate('state.summary !== null'), 'Discovery pool failed to load');
  assert.equal(await evaluate('state.summary.remaining'), 20);
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  await evaluate("applyTheme('dark');window.scrollTo(0,0)");
  let shot = await command('Page.captureScreenshot', {format:'png'});
  await writeFile(path.join(outputDir, 'discovery-home.png'), Buffer.from(shot.data,'base64'));

  await evaluate("document.querySelector('[data-count=\"1\"]').click()");
  await until(() => evaluate('!state.busy && state.revealed.size === 1'), 'Single draw failed');
  assert.equal(await evaluate('state.cards.length'), 1);
  await evaluate("document.querySelector('[data-action=favorite]').click()");
  await until(() => evaluate('state.cards[0].favorite && state.pending.size === 0'), 'Favorite failed');
  await evaluate("document.querySelector('[data-action=to_read]').click()");
  await until(() => evaluate("state.cards[0].read_status==='to_read'"), 'Queue action failed');
  await evaluate("document.querySelector('.card-detail-link').click()");
  assert.equal(await evaluate("document.getElementById('paper-dialog').open"), true);
  assert.equal(await evaluate("document.querySelectorAll('#dialog-content script, #dialog-content img').length"), 0);
  await evaluate("document.querySelector('#paper-dialog .dialog-close').click()");

  await evaluate("document.querySelector('[data-count=\"5\"]').click()");
  await until(() => evaluate('!state.busy && state.cards.length === 5'), 'Five draw failed');
  assert.equal(await evaluate('state.revealed.size'), 0);
  await evaluate("document.querySelector('.card-back').click()");
  assert.equal(await evaluate('state.revealed.size'), 1);
  await evaluate("document.getElementById('save-batch').click()");
  await until(() => evaluate('state.pending.size === 0 && state.cards.filter(c=>c.favorite).length === 1'), 'Save revealed included hidden cards or failed');
  await evaluate("document.getElementById('reveal-all').click()");
  await until(() => evaluate('state.revealed.size === 5'), 'Reveal all failed');

  // A lost response must recover the same saved batch, not consume another ten papers.
  await evaluate(`window.originalFetch=window.fetch; window.lostOnce=false;
    window.fetch=async(...args)=>{const response=await originalFetch(...args);if(String(args[0]).endsWith('/draw')&&!lostOnce){lostOnce=true;await response.text();throw new Error('Simulated lost response');}return response;};
    document.querySelector('[data-count="10"]').click();`);
  await until(() => evaluate('!state.busy && lostOnce'), 'Lost-response simulation did not complete');
  assert.equal(await evaluate('state.cards.length'), 5);
  await evaluate('window.fetch=originalFetch;');
  await evaluate("document.querySelector('[data-count=\"10\"]').click()");
  await until(() => evaluate('!state.busy && state.cards.length === 10'), 'Ten-draw recovery failed');
  assert.equal(await evaluate('state.summary.remaining'), 4);
  assert.equal(await evaluate('new Set(state.cards.map(c=>c.id)).size'),10);
  await evaluate("document.getElementById('reveal-all').click()");
  await until(() => evaluate('state.revealed.size === 10'), 'Ten reveal failed');
  await evaluate('window.savedBatch=state.batch.id;');
  const batchId=await evaluate('state.batch.id');
  await navigate(baseUrl+'discover');
  await until(() => evaluate('state.batch !== null'), 'Saved draw was not restored');
  assert.equal(await evaluate('state.batch.id'),batchId);
  assert.equal(await evaluate('state.revealed.size'),10);
  await evaluate("window.scrollTo(0,0); applyTheme('dark')");
  await evaluate('Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))');
  let layout=await command('Page.getLayoutMetrics');
  shot=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:1360,height:layout.cssContentSize.height,scale:1}});
  await writeFile(path.join(outputDir,'discovery-ten-dark.png'),Buffer.from(shot.data,'base64'));

  // A failed quick-save is visible and can be retried without losing a card.
  await evaluate(`window.originalFetch=window.fetch;window.fetch=async()=>{throw new Error('Simulated offline');};document.querySelector('[data-action=favorite]').click();`);
  await until(()=>evaluate('state.pending.size===0'), 'Save remained disabled');
  assert.equal(await evaluate("document.getElementById('toast').textContent"),await evaluate('T.action_failed'));
  await evaluate("window.fetch=originalFetch; document.getElementById('save-batch').click()");
  await until(()=>evaluate('state.pending.size===0 && state.cards.every(c=>c.favorite)'), 'Batch favorite failed');

  await navigate(baseUrl+'discover');
  await until(()=>evaluate('state.batch !== null'),'Mobile restore failed');
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await evaluate("window.scrollTo(0,0);applyTheme('light')");
  await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  await evaluate('Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))');
  assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);
  shot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'discovery-mobile-light.png'),Buffer.from(shot.data,'base64'));
  await evaluate("document.getElementById('rating-guide').click()");
  assert.equal(await evaluate("document.getElementById('rules-dialog').open"),true);
  await evaluate("document.querySelector('#rules-dialog .dialog-close').click()");
  await evaluate("document.getElementById('skip-animation').click();document.querySelector('[data-count=\"10\"]').click()");
  await until(()=>evaluate('!state.busy && state.cards.length===4'),'Partial draw failed');
  assert.equal(await evaluate('state.revealed.size'),4);
  assert.equal(await evaluate("document.querySelector('[data-count=\"1\"]').disabled"),true);
  await evaluate("document.getElementById('reset-round').click()");
  await until(()=>evaluate('!state.busy && state.summary.remaining===20'),'New round failed');
  await evaluate("document.getElementById('topic').value='no matching paper';document.getElementById('topic').dispatchEvent(new Event('input',{bubbles:true}))");
  await until(()=>evaluate('state.summary && state.summary.remaining===0'),'Empty search failed');
  assert.equal(await evaluate("document.querySelector('[data-count=\"1\"]').disabled"),true);
  // Exercise a real reveal handler with a deterministic fixture card.
  await command('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
  await evaluate(`window.faceAnimations=[];document.addEventListener('animationstart',e=>{if(e.target.matches('.card-front'))window.faceAnimations.push(e.animationName)});document.getElementById('skip-animation').checked=false;document.getElementById('skip-animation').dispatchEvent(new Event('change'));
    window.effectBatch={...state.batch,cards:[{...state.cards[0],rarity:'UR',score:29}]};renderBatch(effectBatch);reveal(effectBatch.cards[0].id);
    applyTheme('dark');document.getElementById('draw-results').scrollIntoView();`);
  assert.equal(await evaluate("document.querySelectorAll('.rarity-spark').length"),22);
  assert.equal(await evaluate("document.querySelector('.rarity-celebration').dataset.tier"),'UR');
  await pause(250);
  shot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'discovery-ur-effects.png'),Buffer.from(shot.data,'base64'));
  await pause(2100);
  assert.deepEqual(await evaluate('window.faceAnimations'),['rare-arrival']);
  assert.equal(await evaluate("document.querySelectorAll('.rarity-fx').length"),0);
  await evaluate("document.getElementById('skip-animation').click()");
  assert.equal(await evaluate("document.querySelectorAll('.rarity-fx,.rarity-celebration').length"),0);
  await command('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await evaluate("document.getElementById('skip-animation').checked=false;renderBatch(effectBatch);reveal(effectBatch.cards[0].id)");
  assert.equal(await evaluate("document.querySelectorAll('.rarity-fx,.rarity-celebration').length"),0);
  await command('Emulation.setEmulatedMedia',{features:[]});
  await evaluate('renderBatch(effectBatch,true)');
  assert.equal(await evaluate("document.querySelectorAll('.rarity-fx,.rarity-celebration').length"),0);
  assert.equal(exceptions.length,0,JSON.stringify(exceptions));
  console.log('PASS: single/five/ten draws, reveal, queue, favorites, batch save, lost-response recovery, persistence, partial draws, new round, empty state, mobile layout; no JavaScript errors.');
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