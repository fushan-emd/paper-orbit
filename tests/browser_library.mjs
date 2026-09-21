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
  await until(() => evaluate("document.readyState === 'complete' && !!document.querySelector('form.paper-tools')"), 'Page did not load');
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
  await navigate(baseUrl);
  assert.equal(await evaluate("document.querySelector('.orbit-nav [aria-current=page]').textContent"),'文献库');
  await evaluate("window.scrollTo(0,0);applyTheme('dark')");
  const heroShot=await command('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(outputDir,'library-orbit-desktop.png'),Buffer.from(heroShot.data,'base64'));
  assert.equal(await evaluate("document.querySelectorAll('article.paper').length"), 20);
  await evaluate("document.querySelector('.reading-details summary').click()");
  assert.equal(await evaluate("document.querySelector('.reading-details').open"), true);
  await evaluate(`window.testForm = document.querySelector('form.paper-tools');
    window.testNote = testForm.querySelector('textarea');
    window.testId = testForm.querySelector('[name=paper_id]').value;
    testNote.value = '浏览器验证笔记'; testNote.dispatchEvent(new Event('input', {bubbles:true}));`);
  assert.equal(await evaluate('hasUnsavedLibraryChanges()'), true);
  assert.equal(await evaluate("!window.dispatchEvent(new Event('beforeunload', {cancelable:true}))"), true);
  await evaluate('testForm.requestSubmit()');
  await until(() => evaluate("testForm.querySelector('.save-feedback').textContent === libraryText.saved"), 'Note was not saved');
  assert.equal(await evaluate('hasUnsavedLibraryChanges()'), false);
  await navigate(baseUrl);
  assert.equal(await evaluate("document.querySelector('form.paper-tools textarea').value"), '浏览器验证笔记');

  // Keep edits made while a previous save request is still in flight.
  await evaluate(`window.testForm = document.querySelector('form.paper-tools');
    window.testNote = testForm.querySelector('textarea');
    window.originalFetch = window.fetch;
    window.fetch = async (...args) => { if (String(args[0]).includes('/paper/update')) await new Promise(r => setTimeout(r, 350)); return originalFetch(...args); };
    testNote.value = 'First saved version'; testNote.dispatchEvent(new Event('input', {bubbles:true}));
    testForm.requestSubmit();
    testNote.value = '浏览器验证笔记'; testNote.dispatchEvent(new Event('input', {bubbles:true}));`);
  assert.equal(await evaluate('hasUnsavedLibraryChanges()'), true);
  await evaluate(`testNote.value = 'Newer unsaved version'; testNote.dispatchEvent(new Event('input', {bubbles:true}));`);
  await until(() => evaluate("!testForm.querySelector('button').disabled"), 'Save never completed');
  assert.equal(await evaluate('hasUnsavedLibraryChanges()'), true);
  assert.equal(await evaluate('testNote.value'), 'Newer unsaved version');

  // Failed saves retain the note, re-enable Save, and keep navigation protection.
  await evaluate(`window.fetch = async () => { throw new Error('Simulated connection failure'); }; testForm.requestSubmit();`);
  await until(() => evaluate("testForm.querySelector('.save-feedback').classList.contains('save-error')"), 'Failure feedback missing');
  assert.equal(await evaluate('testNote.value'), 'Newer unsaved version');
  assert.equal(await evaluate("testForm.querySelector('button').disabled"), false);
  assert.equal(await evaluate('hasUnsavedLibraryChanges()'), true);
  await evaluate('window.fetch = originalFetch; testForm.requestSubmit()');
  await until(() => evaluate('!hasUnsavedLibraryChanges()'), 'Retry failed');

  // Finishing analysis must not reload an unsaved note.
  await evaluate(`(async () => { testNote.value = 'Keep after analysis'; testNote.dispatchEvent(new Event('input', {bubbles:true}));
    observedActiveRun = true;
    window.fetch = async () => new Response(JSON.stringify({running:false,tail:[]}), {headers:{'Content-Type':'application/json'}});
    await refreshRunStatus(); window.fetch = originalFetch; })()`);
  assert.equal(await evaluate("document.getElementById('library-refresh-notice').hidden"), false);
  assert.equal(await evaluate('testNote.value'), 'Keep after analysis');
  await evaluate('testForm.requestSubmit()');
  await until(() => evaluate('!hasUnsavedLibraryChanges()'), 'Final save failed');

  await evaluate("document.getElementById('library').scrollIntoView(); applyTheme('light')");
  let shot = await command('Page.captureScreenshot', {format:'png'});
  await writeFile(path.join(outputDir, 'library-desktop.png'), Buffer.from(shot.data, 'base64'));
  await command('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: false});
  await evaluate("applyTheme('dark'); document.getElementById('library').scrollIntoView()");
  assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true);
  shot = await command('Page.captureScreenshot', {format:'png'});
  await writeFile(path.join(outputDir, 'library-mobile-dark.png'), Buffer.from(shot.data, 'base64'));

  await navigate(baseUrl + '?page=2#library');
  assert.equal(await evaluate("document.querySelectorAll('article.paper').length"), 2);
  assert.equal(await evaluate("document.querySelector('form.filters').action.endsWith('/#library')"), true);
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  console.log('PASS: pagination, reading details, persistent notes, in-flight edits, failed-save retry, refresh protection, desktop/mobile themes; no JavaScript errors.');
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