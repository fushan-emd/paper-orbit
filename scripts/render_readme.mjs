// Browser smoke checks using Node 22+ and a locally installed Edge/Chrome; no npm dependencies.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';

const [browserPath, inputDir, outputDir] = process.argv.slice(2);
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

  await command('Emulation.setDeviceMetricsOverride',{width:1600,height:1280,deviceScaleFactor:1,mobile:false});
  const pictures={};
  for(const [key,file] of Object.entries({select:'selection-light.png',compose:'composer-light.png',result:'evidence-light.png'})){
    pictures[key]='data:image/png;base64,'+(await readFile(path.join(inputDir,file))).toString('base64');
  }
  for(const lang of ['zh','en']){
    const zh=lang==='zh';
    const words=zh?{
      title:'让多篇文献，汇聚成新的研究问题。',sub:'选择 2–6 张文献卡，连接方法与证据，形成可检验的研究假设。',
      steps:['选择文献卡','提出研究问题','跨文献汇聚分析','核对证据与验证方案'],
      select:'组建你的文献组合',compose:'带着具体问题，连接研究线索',result:'从组合依据，到可执行的验证思路',
      tag:'多卡片汇聚分析',foot:'真实浅色界面 · 合成文献与模拟 AI 演示 · 生成内容是待验证假设',
      chips:['2–6 篇文献','来源片段可追溯','实验 · 指标 · 风险']
    }:{
      title:'Connect papers. Develop research questions.',sub:'Combine 2–6 paper cards into testable hypotheses with source-linked reasoning.',
      steps:['Select papers','Ask a question','Synthesize across papers','Review evidence & tests'],
      select:'Build your paper combination',compose:'Connect ideas around a focused question',result:'From combined evidence to a testable plan',
      tag:'MULTI-PAPER SYNTHESIS',foot:'Actual light-mode UI · Synthetic papers and mocked AI · Hypotheses require validation',
      chips:['2–6 papers','Traceable source excerpts','Experiments · Metrics · Risks']
    };
    const tile=(cls,label,title,img)=>`<section class="tile ${cls}"><div class="tile-head"><span>${label}</span><h2>${title}</h2><i>•••</i></div><div class="shot"><img src="${pictures[img]}" alt="${title}"></div></section>`;
    const html=`<!doctype html><html><head><meta charset="utf-8"><style>
      *{box-sizing:border-box}html,body{margin:0;width:1600px;height:1280px;overflow:hidden}body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#fbfbfe;color:#211d30;padding:48px 62px 26px}
      .top{display:flex;justify-content:space-between;align-items:center}.brand{font-size:25px;letter-spacing:3px;font-weight:500}.brand b{font-size:38px;color:#7550bd;vertical-align:middle;margin-right:12px;font-weight:400}.tag{font-size:13px;letter-spacing:2px;border:1px solid #e2d9f1;padding:10px 16px;border-radius:30px;color:#745398;background:#fff}
      h1{font-size:${zh?54:52}px;letter-spacing:${zh?'-1px':'-2px'};line-height:1.25;margin:31px 0 14px;font-weight:650}.sub{font-size:23px;color:#716b80;margin:0}.chips{display:flex;gap:12px;margin-top:23px}.chips span{font-size:14px;padding:8px 14px;background:#f0ecf8;border-radius:7px;color:#6f5395}
      .steps{display:flex;align-items:center;justify-content:space-between;margin:30px 0 28px;padding-top:23px;border-top:1px solid #e6e2ed}.step{font-size:17px;color:#51465f}.step b{font:14px 'Segoe UI';color:#8c71b1;margin-right:12px}.arrow{color:#b2a6c4;font-size:23px}
      .stage{display:grid;grid-template-columns:555px 1fr;grid-template-rows:325px 374px;gap:22px}.tile{border:1px solid #e0dce9;border-radius:16px;background:white;overflow:hidden;box-shadow:0 12px 26px #36225409}.tile-head{height:75px;padding:15px 21px;position:relative;border-bottom:1px solid #eeebf4}.tile-head>span{font-size:10px;letter-spacing:1.5px;color:#967aaf}.tile-head h2{font-size:18px;line-height:1.5;margin:4px 0;font-weight:600}.tile-head i{position:absolute;right:20px;top:18px;color:#c8bfd7;font-size:13px;font-style:normal}.shot{padding:16px;background:#fcfbff;height:calc(100% - 75px);overflow:hidden}.shot img{display:block;width:100%;height:auto;border:1px solid #eeeaf4;border-radius:8px}.result{grid-column:2;grid-row:1/3}.result .shot{padding:20px}.select .shot img{width:950px;max-width:none}.compose .shot img{width:100%}footer{display:flex;justify-content:space-between;color:#93899f;font-size:12px;letter-spacing:.3px;margin-top:24px}footer b{font-weight:500;color:#786785}
    </style></head><body><div class="top"><div class="brand"><b>✧</b>PAPER ORBIT</div><div class="tag">${words.tag}</div></div><h1>${words.title}</h1><p class="sub">${words.sub}</p><div class="chips">${words.chips.map(x=>'<span>'+x+'</span>').join('')}</div><div class="steps">${words.steps.map((x,i)=>'<span class="step"><b>0'+(i+1)+'</b>'+x+'</span>').join('<span class="arrow">→</span>')}</div><div class="stage">${tile('select','01 / PAPER CARDS',words.select,'select')}${tile('compose','02 / RESEARCH QUESTION',words.compose,'compose')}${tile('result','03 / SYNTHESIS & VALIDATION',words.result,'result')}</div><footer><span>${words.foot}</span><b>LOCAL FIRST / MIT / BETA</b></footer></body></html>`;
    const tree=await command('Page.getFrameTree');
    await command('Page.setDocumentContent',{frameId:tree.frameTree.frame.id,html});
    await evaluate('Promise.all([...document.images].map(i=>i.decode()))');
    await evaluate('document.fonts.ready');
    assert.equal(await evaluate('document.querySelector("footer").getBoundingClientRect().bottom <= 1280'),true);
    const shot=await command('Page.captureScreenshot',{format:'png'});
    await writeFile(path.join(outputDir,'hero-'+lang+'.png'),Buffer.from(shot.data,'base64'));
  }
  assert.equal(exceptions.length,0,JSON.stringify(exceptions));
  console.log('Rendered bilingual light-mode product compositions.');
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