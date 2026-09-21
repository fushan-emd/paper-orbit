'use strict';
const $ = id => document.getElementById(id);
const state = {pool:'unread', query:'', ai_only:true, busy:false, cards:[], revealed:new Set(), pending:new Set(), summary:null, request:null, batch:null};
let summaryVersion = 0;
let toastTimer;
let revealTimers = [];
let topicTimer;
function node(tag, cls, value) { const n = document.createElement(tag); if(cls) n.className = cls; if(value != null) n.textContent = String(value); return n; }
function message(text) { $('toast').textContent = text; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4200); }
function options() { return {pool:state.pool, q:state.query, ai_only:state.ai_only?'1':'0'}; }
function shortMotion() { return $('skip-animation').checked || matchMedia('(prefers-reduced-motion: reduce)').matches; }
function applyTheme(theme) { document.documentElement.dataset.theme = theme; $('theme-switch').setAttribute('aria-pressed', String(theme==='light')); try { localStorage.setItem('literature-radar-theme',theme); } catch (_) {} }
try { applyTheme(localStorage.getItem('literature-radar-theme') || 'dark'); } catch (_) { applyTheme('dark'); }
$('theme-switch').addEventListener('click', () => applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
$('skip-animation').checked = matchMedia('(prefers-reduced-motion: reduce)').matches;
$('skip-animation').addEventListener('change', () => document.body.classList.toggle('no-motion',shortMotion()));
async function api(path, data) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(path, data ? {method:'POST',headers:{'Accept':'application/json'},body:new URLSearchParams(data),signal:controller.signal} : {signal:controller.signal});
    const result = await response.json();
    if(!response.ok) throw new Error(result.error || 'HTTP '+response.status);
    if(result.ok===false) throw new Error(result.error || 'Request failed');
    return result;
  } finally { clearTimeout(timeout); }
}
function controls() {
  document.querySelectorAll('[data-count]').forEach(b => b.disabled=state.busy || flow.collecting || !flow.checked || !state.summary || (collectionReady() && state.summary.remaining===0));
  document.querySelectorAll('[data-pool]').forEach(b => b.disabled=state.busy);
  $('topic').disabled=state.busy; $('ai-only').disabled=state.busy;
  $('reset-round').disabled=state.busy || !state.summary || state.summary.seen===0;
  $('save-batch').disabled=state.busy || state.pending.size>0 || !state.cards.some(c=>state.revealed.has(c.id) && !c.favorite);
}
function renderSummary(summary) {
  state.summary=summary;
  $('remaining').textContent=summary.remaining;
  for(const tier of ['N','R','SR','SSR','UR']) $('tier-'+tier).textContent=summary.tiers[tier];
  if(summary.remaining) $('pool-status').textContent=T.pool_hint.replace('{seen}',summary.seen);
  else $('pool-status').textContent=summary.pool_total===0?T.no_library:T.pool_empty;
  controls();
}
async function refreshSummary() {
  const version=++summaryVersion;
  state.summary=null; controls();
  try { const result=await api('/api/discovery?'+new URLSearchParams(options())); if(version===summaryVersion) renderSummary(result.summary); }
  catch (_) { if(version===summaryVersion) { $('pool-status').textContent=T.load_failed; message(T.load_failed); } }
}
function setPool(pool) {
  if(state.busy) return;
  state.pool=pool; state.request=null;
  document.querySelectorAll('[data-pool]').forEach(b=>{b.classList.toggle('selected',b.dataset.pool===pool);b.setAttribute('aria-pressed',String(b.dataset.pool===pool));});
  refreshSummary();
}
document.querySelectorAll('[data-pool]').forEach(b=>b.addEventListener('click',()=>setPool(b.dataset.pool)));
$('ai-only').addEventListener('change',()=>{state.ai_only=$('ai-only').checked;state.request=null;refreshSummary();});
$('topic').addEventListener('input',()=>{
  clearTimeout(topicTimer); state.summary=null;controls();
  // Invalidate responses for the previous keyword immediately.
  ++summaryVersion;
  topicTimer=setTimeout(()=>{state.query=$('topic').value.trim();state.request=null;refreshSummary();},280);
});
function statusLabel(card) { return ['to_read','reading','read','reproduce'].includes(card.read_status) ? T.queued : T.queue; }
function updateBatchSummary() {
  const shown=state.cards.filter(c=>state.revealed.has(c.id));
  $('reveal-progress').textContent=state.cards.length?T.reveal_progress.replace('{seen}',shown.length).replace('{total}',state.cards.length):'';
  const counts={}; shown.forEach(c=>counts[c.rarity]=(counts[c.rarity]||0)+1);
  const tiers=['UR','SSR','SR','R','N','UNRATED'].filter(t=>counts[t]).map(t=>(t==='UNRATED'?T.unrated:t)+' ×'+counts[t]);
  $('batch-summary').textContent=shown.length ? tiers.join('  ·  ')+'  /  '+T.saved_count.replace('{count}',state.cards.filter(c=>c.favorite).length) : state.cards.length?T.reveal_hint:'';
  $('reveal-all').hidden=!state.cards.length || shown.length===state.cards.length;
  $('save-batch').hidden=!shown.length;
  controls();
}
function actionButton(text, handler, cls='') { const b=node('button',cls,text); b.type='button';b.addEventListener('click',handler);return b; }
function front(card) {
  const f=node('div','card-front');
  const art=node('div','card-art');
  art.append(node('b','card-rarity',card.rarity==='UNRATED'?'—':card.rarity),node('small','',card.score==null?T.unrated:'AI '+card.score+' / 30'));
  const body=node('div','card-body');
  body.append(node('div','card-meta',(card.journal || card.source)+' · '+(card.published?card.published.slice(0,4):'—')));
  body.append(node('h3','card-title',card.title));
  const tags=node('div','card-tags'); card.tags.slice(0,2).forEach(t=>tags.append(node('span','',t)));body.append(tags);
  body.append(node('p','card-summary',card.analysis.summary || card.abstract || T.no_abstract));
  body.append(node('div','card-reason',card.score==null?T.pending_rating:T.ai_match));
  body.append(node('small','card-evidence-scope',['retracted','retraction_notice'].includes(card.retraction_status)?T.retracted_notice:card.publication_kind==='preprint'?T.preprint_notice:card.retraction_status==='not_flagged_by_source'?T.source_status:T.status_unverified));
  const more=actionButton(T.read_details+' ↗',()=>showPaper(card),'card-detail-link');body.append(more);
  const actions=node('div','card-actions');
  const save=actionButton(card.favorite?'♥ '+T.saved:'♡ '+T.save,()=>act(card.id,card.favorite?'unfavorite':'favorite'),card.favorite?'is-saved':'');
  save.dataset.action='favorite';save.setAttribute('aria-pressed',String(card.favorite));
  const queue=actionButton(statusLabel(card),()=>act(card.id,'to_read'),card.read_status!=='new'?'is-saved':'');
  queue.dataset.action='to_read';
  queue.disabled=state.pending.has(card.id)||['to_read','reading','read','reproduce'].includes(card.read_status);
  save.disabled=state.pending.has(card.id);
  const open=actionButton('↗',()=>showPaper(card));open.setAttribute('aria-label',T.read_details);
  actions.append(save,queue,open);f.append(art,body,actions);return f;
}
function renderCard(card,index) {
  const wrapper=node('article','research-card'); wrapper.id='draw-card-'+card.id;wrapper.style.setProperty('--i',index);
  const back=actionButton('',()=>reveal(card.id),'card-back');
  back.setAttribute('aria-label',T.reveal_card+' '+(index+1));
  back.append(node('span','back-number',String(index+1).padStart(2,'0')+' / PAPER ORBIT'),node('span','back-orbit','✧'),node('b','','DISCOVER'),node('small','',T.tap_reveal));
  wrapper.append(back);
  if(state.revealed.has(card.id)) {back.hidden=true;wrapper.dataset.tier=card.rarity;wrapper.append(front(card));}
  return wrapper;
}
let celebrationTimer;
let celebrationRank=0;
function clearRarityEffects(){
  clearTimeout(celebrationTimer);celebrationRank=0;
  document.querySelectorAll('.rarity-fx,.rarity-celebration').forEach(el=>el.remove());
  document.querySelectorAll('.rare-reveal').forEach(el=>el.classList.remove('rare-reveal'));
}
function celebrateRarity(card,wrapper){
  if(shortMotion()||!['SR','SSR','UR'].includes(card.rarity))return;
  wrapper.classList.add('rare-reveal');
  const fx=node('div','rarity-fx');fx.setAttribute('aria-hidden','true');
  fx.append(node('span','rarity-ring'),node('span','rarity-ring second'),node('span','rarity-beam'));
  const particles=card.rarity==='UR'?22:card.rarity==='SSR'?14:8;
  for(let i=0;i<particles;i++){
    const spark=node('i','rarity-spark');const angle=(i/particles)*Math.PI*2;
    spark.style.setProperty('--dx',Math.cos(angle)*(85+i%4*14)+'px');
    spark.style.setProperty('--dy',Math.sin(angle)*(100+i%3*22)+'px');
    spark.style.setProperty('--delay',i%5*35+'ms');fx.append(spark);
  }
  wrapper.append(fx);
  setTimeout(()=>{fx.remove();wrapper.classList.remove('rare-reveal');},1900);
  const rank=card.rarity==='UR'?2:card.rarity==='SSR'?1:0;
  if(!rank||rank<celebrationRank)return;
  celebrationRank=rank;clearTimeout(celebrationTimer);
  document.querySelector('.rarity-celebration')?.remove();
  const banner=node('div','rarity-celebration');banner.dataset.tier=card.rarity;banner.setAttribute('role','status');
  banner.append(node('span','celebration-sigil',card.rarity==='UR'?'✧':'✦'),node('b','',card.rarity),node('span','',card.rarity==='UR'?T.ultra_discovery:T.rare_discovery));
  document.body.append(banner);
  celebrationTimer=setTimeout(()=>{banner.remove();celebrationRank=0;},2200);
}
$('skip-animation').addEventListener('change',()=>{if(shortMotion())clearRarityEffects();});
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',event=>{if(event.matches)clearRarityEffects();});
document.addEventListener('visibilitychange',()=>{if(document.hidden)clearRarityEffects();});
function reveal(id) {
  if(state.revealed.has(id)) return;
  const card=state.cards.find(c=>c.id===id); const wrapper=$('draw-card-'+id);
  if(!card || !wrapper) return;
  state.revealed.add(id);wrapper.dataset.tier=card.rarity;
  const back=wrapper.querySelector('.card-back');const focused=document.activeElement===back;back.hidden=true;
  const face=front(card);
  if(!shortMotion())face.style.animation=['SR','SSR','UR'].includes(card.rarity)?'rare-arrival 1.1s ease-out both':'reveal-in .55s ease both';
  wrapper.append(face);celebrateRarity(card,wrapper);
  if(focused) wrapper.querySelector('.card-detail-link').focus({preventScroll:true});
  updateBatchSummary();
}
function renderBatch(batch,restored=false) {
  clearRarityEffects();
  revealTimers.forEach(clearTimeout);revealTimers=[];
  state.batch=batch;state.cards=batch?batch.cards:[];state.revealed=new Set(restored?state.cards.map(c=>c.id):[]);
  $('card-grid').replaceChildren(...state.cards.map(renderCard));
  $('card-grid').classList.toggle('single-draw',state.cards.length===1);
  $('empty-stage').hidden=!!state.cards.length;
  $('batch-count').textContent=state.cards.length?' / '+String(state.cards.length).padStart(2,'0'):'';
  $('results-heading').firstChild.textContent=restored?T.last_results+' ':T.results+' ';
  updateBatchSummary();
  if(state.cards.length===1 && !restored) revealTimers.push(setTimeout(()=>reveal(state.cards[0].id),shortMotion()?0:220));
  if(shortMotion() && !restored) state.cards.forEach(c=>reveal(c.id));
}
async function performDraw(count) {
  if(state.busy || !state.summary?.remaining) return;
  state.busy=true;controls();document.body.classList.add('is-drawing');
  $('pool-status').textContent=T.drawing;
  ++summaryVersion;
  if(!state.request || state.request.count!==count) state.request={count,request_id:crypto.randomUUID(),...options()};
  try {
    const [result]=await Promise.all([api('/api/discovery/draw',state.request),new Promise(r=>setTimeout(r,shortMotion()?0:300))]);
    state.request=null;renderBatch(result.batch);renderSummary(result.summary);
    if(result.batch.cards.length<count) message(T.partial_draw.replace('{count}',result.batch.cards.length));
    $('draw-results').scrollIntoView({behavior:shortMotion()?'instant':'smooth',block:'start'});
  } catch (_) {message(T.draw_failed);$('pool-status').textContent=T.draw_failed;}
  finally {state.busy=false;document.body.classList.remove('is-drawing');controls();}
}
document.querySelectorAll('[data-count]').forEach(b=>b.addEventListener('click',()=>requestDraw(Number(b.dataset.count))));
$('reveal-all').addEventListener('click',()=>{state.cards.forEach((c,i)=>revealTimers.push(setTimeout(()=>reveal(c.id),shortMotion()?0:i*65)));});
async function act(id,action,quiet=false) {
  if(state.pending.has(id)) return false;
  state.pending.add(id);updateCard(id);const owned=flow.owned.cards.find(c=>c.id===id);if(owned)syncOwnedCard(owned);controls();
  try {
    const result=await api('/api/discovery/action',{paper_id:id,action});
    const index=state.cards.findIndex(c=>c.id===id);if(index!==-1)state.cards[index]=result.card;
    syncOwnedCard(result.card);
    if(!quiet) message(action==='unfavorite'?T.unsaved:action==='to_read'?T.queue_saved:T.favorite_saved);
    return true;
  } catch (_) {if(!quiet)message(T.action_failed);return false;}
  finally {state.pending.delete(id);updateCard(id);updateBatchSummary();
    const owned=flow.owned.cards.find(c=>c.id===id);if(owned)syncOwnedCard(owned);
    if(flow.view==='warehouse'){clearTimeout(warehouseTimer);warehouseTimer=setTimeout(()=>loadWarehouse(flow.owned.page),250);}
  }
}
function updateCard(id) {
  const card=state.cards.find(c=>c.id===id);const wrapper=$('draw-card-'+id);
  if(!card || !wrapper || !state.revealed.has(id)) return;
  const focused=wrapper.contains(document.activeElement)?document.activeElement.dataset.action:null;
  const old=wrapper.querySelector('.card-front');const replacement=front(card);replacement.style.animation='none';old.replaceWith(replacement);
  if(focused)wrapper.querySelector('[data-action="'+focused+'"]').focus({preventScroll:true});
  if($('paper-dialog').open && $('paper-dialog').dataset.paper===String(id)) fillDialog(card);
}
$('save-batch').addEventListener('click',async()=>{
  const targets=state.cards.filter(c=>state.revealed.has(c.id)&&!c.favorite);
  const results=await Promise.all(targets.map(c=>act(c.id,'favorite',true)));
  const succeeded=results.filter(Boolean).length;
  message(succeeded===targets.length?T.batch_saved.replace('{count}',succeeded):T.batch_failed.replace('{count}',succeeded));
});
$('reset-round').addEventListener('click',async()=>{
  if(state.busy)return;
  state.busy=true;controls();++summaryVersion;
  try {const result=await api('/api/discovery/reset',options());state.request=null;renderSummary(result.summary);message(T.reset_done);}
  catch(_){message(T.action_failed);}
  finally{state.busy=false;controls();}
});
function fillDialog(card) {
  const content=$('dialog-content');content.replaceChildren();content.dataset.tier=card.rarity;
  content.append(node('span','dialog-rarity',card.rarity==='UNRATED'?T.unrated:card.rarity+' · AI '+card.score+'/30'));
  const title=node('h2','',card.title);title.id='dialog-title';content.append(title);
  content.append(node('p','',(card.journal||card.source)+' · '+(card.published||'—')+(card.doi?'\nDOI: '+card.doi:'')));
  content.append(node('p','composer-note',T.abstract_scope+' '+(['retracted','retraction_notice'].includes(card.retraction_status)?T.retracted_notice:card.publication_kind==='preprint'?T.preprint_notice:card.retraction_status==='not_flagged_by_source'?T.source_status:T.status_unverified)));
  const provenance=card.analysis.rating_provenance;
  if(provenance)content.append(node('p','composer-note',[provenance.model,provenance.rubric_version,provenance.rated_at].filter(Boolean).join(' · ')));
  const dimensions=card.analysis.rating_dimensions;
  if(card.score!==null&&dimensions&&typeof dimensions==='object'&&['relevance','methods','evidence','reusability'].every(k=>Number.isInteger(dimensions[k]))) {
    const grid=node('div','rubric-grid');
    for(const [key,max] of [['relevance',12],['methods',8],['evidence',6],['reusability',4]]) {const cell=node('div');cell.append(node('b','',dimensions[key]+'/'+max),node('span','',T[key]));grid.append(cell);}content.append(grid);
  }
  for(const [key,label] of [['why_read','why_read'],['abstract','abstract'],['detailed_summary','detailed_summary'],['method_clues','methods'],['data_task_clues','data_tasks'],['method_flow','method_flow'],['follow_up_prompts','questions'],['evaluation','evaluation']]) {
    const value=key==='abstract'?card.abstract:card.analysis[key]; if(!value || Array.isArray(value)&&!value.length)continue;
    content.append(node('h3','',T[label]));
    if(Array.isArray(value)) {const list=node(key==='method_flow'?'ol':'ul');value.forEach(v=>list.append(node('li','',v)));content.append(list);}
    else content.append(node('p','',value));
  }
  const actions=node('div','dialog-actions');
  const save=actionButton(card.favorite?'♥ '+T.saved:'♡ '+T.save,()=>act(card.id,card.favorite?'unfavorite':'favorite'),'small-button');save.disabled=state.pending.has(card.id);actions.append(save);
  const queue=actionButton(statusLabel(card),()=>act(card.id,'to_read'),'small-button');queue.disabled=state.pending.has(card.id)||['to_read','reading','read','reproduce'].includes(card.read_status);actions.append(queue);
  const library=node('a','small-button',T.open_library+' ↗');library.href='/?q='+encodeURIComponent(card.doi||card.title)+'#paper-'+card.id;actions.append(library);
  if(card.url!=='#'){const source=node('a','small-button',T.original+' ↗');source.href=card.url;source.target='_blank';source.rel='noopener noreferrer';actions.append(source);}
  content.append(actions);
}
function showPaper(card) { const current=(flow.view==='warehouse'?flow.owned.cards:state.cards).find(c=>c.id===card.id)||card;$('paper-dialog').dataset.paper=current.id;fillDialog(current);$('paper-dialog').showModal(); }
$('rating-guide').addEventListener('click',()=>$('rules-dialog').showModal());
document.querySelectorAll('#paper-dialog, #rules-dialog').forEach(d=>{
  d.querySelector('.dialog-close').addEventListener('click',()=>d.close());
  d.addEventListener('click',event=>{if(event.target===d){const r=d.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)d.close();}});
});
async function boot() {
  const version=++summaryVersion;
  try {const result=await api('/api/discovery?'+new URLSearchParams({...options(),latest:'1'}));if(version!==summaryVersion)return;renderSummary(result.summary);if(result.batch)renderBatch(result.batch,true);}
  catch(_){$('pool-status').textContent=T.load_failed;message(T.load_failed);}
}
boot();