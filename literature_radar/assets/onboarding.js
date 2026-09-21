/* Navigation is progress, never implicit completion. No network collection or AI calls. */
(() => {
  const initial=window.orbitTourState, zh=initial.zh;
  let active=initial.active, step=initial.step, busy=false, collapsed=false;
  const routes=['/discover','/?settings=1','/discover','/discover','/discover#warehouse','/discover#lab','/#library','/manage'];
  const targets=['.hero','#settings-panel','.collection-panel','.draw-console','#warehouse-view','#lab-view','#library','main'];
  const copy=zh?[
    ['欢迎来到 Paper Orbit','这次我们边看边走。教程会跟着你进入不同页面，保存设置、刷新或重新启动都不会丢失进度。','点击下一步前往设置；你也可以收起卡片，自由操作页面。'],
    ['01 · 配置你的研究方向','在这里检查关键词、检索式和文献来源。需要 AI 时，将分析方式选为 AI，填写自己的 API key。','配置后点击页面的“保存配置”。保存不会结束教程；不使用 AI 也可以继续。'],
    ['02 · 先搜集，再抽卡','这里将真实文献搜集到你的牌库。第一次使用先检查研究方向，再主动点击搜集。','启用 AI 分析可能产生费用。教程不会替你发起搜集；已有文献可选择使用现有牌库。'],
    ['03 · 翻开你的文献卡','单抽、五连和十连都在这里。翻卡后可以查看解读、收藏和打开原文。','N–UR 表示阅读优先级，不是质量认证。无 AI 文献时取消“仅 AI”筛选；空牌库也能继续参观。'],
    ['04 · 仓库保存你的发现','抽过的卡会保存在这里，可以筛选、收藏和标记阅读状态。选择 2–6 张卡加入科研想法工作台。','仓库为空时先了解界面即可，不必为了完成教程进行抽卡。'],
    ['05 · 从文献组合到研究问题','在这里查看选中的卡片，输入研究问题，主动点击生成后由 AI 提出待验证假设。','会发送选中文献信息和研究问题，不发送个人笔记；调用可能收费，结果需核查证据和新颖性。'],
    ['06 · 在文献库深入阅读','文献库保留全部搜集结果，可以搜索、查看原文、写笔记、收藏并管理阅读进度。','离开页面前确认笔记已保存；教程卡片可以收起，不影响你阅读和编辑。'],
    ['07 · 管理数据与任务','这里可以备份、恢复、导出文献，查看 AI 用量和取消任务。恢复前会自动备份当前数据库。','取消不能撤回已发送的 AI 请求。点击完成才结束本次教程；之后可从“?”重新开始。']
  ]:[
    ['Welcome to Paper Orbit','Explore the actual pages with a guide that follows you. Saving settings, refreshing or restarting keeps your progress.','Continue to Settings, or collapse this card to explore freely.'],
    ['01 · Set your research direction','Review keywords, queries and sources. For AI, select AI analysis and add your API key.','Use Save configuration on the page. Saving does not end the tour; AI is optional.'],
    ['02 · Collect before you draw','This panel collects real papers into your library. Review your topic before starting a collection.','AI analysis may cost money. The guide never starts collection for you; you can use an existing library.'],
    ['03 · Reveal your paper cards','Draw one, five or ten cards, then read analyses, favorite discoveries and open the original sources.','N–UR mean reading priority, not quality. Disable AI-only if needed. An empty library does not block the tour.'],
    ['04 · Keep your discoveries','Drawn cards stay here. Filter, favorite and track reading; select 2–6 cards for the idea lab.','You can explore an empty warehouse without drawing any cards.'],
    ['05 · Combine papers into questions','Review your selected cards, enter a research question, and explicitly generate testable AI hypotheses.','Paper details and your question go to AI; private notes do not. Calls may cost money; verify evidence and novelty.'],
    ['06 · Read in your library','Search all collected papers, open sources, write notes, favorite and track progress.','Check that notes are saved before leaving. Collapse the guide while reading or editing.'],
    ['07 · Manage data and tasks','Back up, restore and export papers, inspect AI usage and cancel tasks. Restore first backs up the current database.','Cancellation cannot recall sent AI requests. Finish explicitly ends this tour; use “?” to restart anytime.']
  ];
  const panel=document.createElement('aside');panel.id='orbit-tour';panel.hidden=true;
  panel.setAttribute('aria-label',zh?'跟随式教程':'Guided tour');
  panel.innerHTML=`<header><span>✧ PAPER ORBIT <b id="tour-count"></b></span><button id="tour-collapse" type="button"></button></header><div id="tour-body"><h2 id="tour-title"></h2><p id="tour-copy"></p><p id="tour-tip"></p><p id="tour-error" role="alert" hidden></p><footer><button id="tour-skip" type="button">${zh?'跳过教程':'Skip tour'}</button><div><button id="tour-back" type="button">${zh?'上一步':'Back'}</button><button id="tour-next" type="button"></button></div></footer></div>`;
  document.body.append(panel);
  const get=id=>document.getElementById(id);
  const launch=document.createElement('button');launch.id='tour-launch';launch.type='button';launch.textContent='?';launch.title=zh?'重新开始教程':'Restart guide';launch.setAttribute('aria-label',launch.title);document.body.append(launch);
  function infer(){if(location.pathname.startsWith('/manage'))return 7;if(location.pathname==='/')return new URLSearchParams(location.search).has('settings')?1:6;if(location.hash==='#warehouse')return 4;if(location.hash==='#lab')return 5;return step===3?3:2;}
  function render(scroll=false){
    panel.hidden=!active;launch.hidden=active||!!get('open-tutorial');
    document.body.classList.toggle('tour-active',active);panel.dataset.step=String(step);
    document.querySelectorAll('.tour-target').forEach(el=>el.classList.remove('tour-target'));
    if(!active)return;
    get('tour-count').textContent=`${step+1} / ${copy.length}`;
    get('tour-title').textContent=copy[step][0];get('tour-copy').textContent=copy[step][1];get('tour-tip').textContent=copy[step][2];
    get('tour-body').hidden=collapsed;get('tour-collapse').textContent=collapsed?(zh?'展开':'Expand'):(zh?'收起':'Collapse');get('tour-collapse').setAttribute('aria-expanded',String(!collapsed));
    get('tour-back').disabled=busy||step===0;get('tour-next').textContent=step===7?(zh?'完成教程 ✓':'Finish ✓'):(zh?'下一步 →':'Continue →');
    const target=document.querySelector(targets[step]);
    if(target){target.classList.add('tour-target');if(scroll)target.scrollIntoView({block:'start',behavior:'instant'});}
  }
  async function save(next,enabled){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
    try{const response=await fetch('/onboarding/progress',{method:'POST',body:new URLSearchParams({step:String(next),active:enabled?'1':'0'}),signal:controller.signal});if(!response.ok)throw new Error('save');}
    finally{clearTimeout(timer);}
  }
  async function transition(next,enabled=true,destination=null){
    if(busy)return false;busy=true;panel.querySelectorAll('button').forEach(b=>b.disabled=true);get('tour-error').hidden=true;
    try{await save(next,enabled);step=next;active=enabled;
      if(destination){const url=new URL(destination,location.href);if(url.pathname!==location.pathname||url.search!==location.search){location.href=url.href;return true;}if(url.hash!==location.hash)location.hash=url.hash;}
      render(true);return true;
    }catch(_){get('tour-error').hidden=false;get('tour-error').textContent=zh?'进度未能保存，请重试。当前教程仍保留。':'Could not save progress. Retry; the tour remains active.';return false;}
    finally{busy=false;panel.querySelectorAll('button').forEach(b=>b.disabled=false);render();}
  }
  const start=()=>transition(0,true,routes[0]);window.orbitTour={start};launch.onclick=start;
  if(get('open-tutorial'))get('open-tutorial').onclick=start;
  get('tour-next').onclick=()=>step===7?transition(step,false):transition(step+1,true,routes[step+1]);
  get('tour-back').onclick=()=>{if(step>0)transition(step-1,true,routes[step-1]);};
  get('tour-skip').onclick=()=>transition(step,false);
  get('tour-collapse').onclick=()=>{collapsed=!collapsed;render();};
  // Normal links remain usable. Their destination page restores the saved tour.
  window.addEventListener('hashchange',()=>{if(active&&!busy){const next=infer();if(next!==step)transition(next);else render(true);}});
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  if(active&&(step!==0||location.pathname!=='/discover'||['#warehouse','#lab'].includes(location.hash))&&infer()!==step)transition(infer());else render(active);
})();
