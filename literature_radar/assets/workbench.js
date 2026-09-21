// Collection, owned-card warehouse and evidence-grounded idea workbench.
const flow={checked:false,ready:false,skip:false,collecting:false,collectionJob:null,collectionRequest:null,waitingCount:null,
  owned:{cards:[],page:1,pages:1},selected:new Map(),workspace:'',draftLoaded:false,view:'discover',
  ideaRunning:false,ideaJob:null,ideaRequest:null,history:[],activeResult:null};
let collectionTimer,ideaTimer,warehouseVersion=0,warehouseTimer;
function collectionReady(){return flow.ready||flow.skip;}
function formatted(template,values){return Object.entries(values).reduce((text,[key,value])=>text.replaceAll('{'+key+'}',String(value)),template);}
function renderCollection(result){
  flow.checked=true;flow.ready=result.fresh;flow.collectionJob=result.job;
  const job=result.job;flow.collecting=!!job&&job.status==='running';
  let text=T.collection_due;
  if(flow.skip&&!flow.collecting)text=T.collection_skip;
  else if(flow.collecting)text=T.collection_running;
  else if(job&&['succeeded','partial'].includes(job.status)&&result.fresh){
    text=formatted(T.collection_done,job.result);if(Number.isInteger(job.result.ai_scored))text+=' '+formatted(T.collection_scoring,job.result);if(job.status==='partial')text+=' '+T.collection_partial;
  }else if(job&&['failed','interrupted','cancelled'].includes(job.status))text=T['error_'+job.result?.error_code]||T.collection_failed;
  $('collection-message').textContent=text;
  $('collection-log-box').hidden=!job;
  $('collection-log').textContent=job?(job.log||[]).join('\n'):'';
  $('collect-now').disabled=flow.collecting||state.busy;
  $('use-existing').hidden=flow.ready||flow.skip||flow.collecting;
  controls();
}
async function loadCollection(){
  try{const result=await api('/api/collection');renderCollection(result);if(flow.collecting)watchCollection();}
  catch(_){$('collection-message').textContent=T.collection_check_failed;flow.checked=true;controls();}
}
async function requestDraw(count){
  if(state.busy||flow.collecting)return;
  if(collectionReady()){performDraw(count);return;}
  flow.waitingCount=count;await prepareCollection(false);
}
async function prepareCollection(force){
  if(flow.collecting)return;
  flow.skip=false;flow.collecting=true;controls();$('collect-now').disabled=true;$('use-existing').hidden=true;
  const mode=force?'1':'0';
  if(!flow.collectionRequest||flow.collectionRequest.force!==mode)flow.collectionRequest={force:mode,request_id:crypto.randomUUID()};
  $('collection-message').textContent=T.collection_wait;
  try{
    const result=await api('/api/collection/ensure',flow.collectionRequest);flow.collectionRequest=null;renderCollection(result);
    if(flow.collecting)watchCollection();
    else if(flow.ready)await continueAfterCollection();
    else flow.waitingCount=null;
  }catch(_){flow.collecting=false;flow.waitingCount=null;$('collection-message').textContent=T.collection_failed;$('collect-now').disabled=false;$('use-existing').hidden=false;controls();}
}
function watchCollection(){clearTimeout(collectionTimer);collectionTimer=setTimeout(pollCollection,1200);}
async function pollCollection(){
  try{
    const result=await api('/api/collection');renderCollection(result);
    if(flow.collecting)watchCollection();
    else if(flow.ready)await continueAfterCollection();
    else{flow.waitingCount=null;await refreshSummary();}
  }catch(_){$('collection-message').textContent=T.collection_check_failed;watchCollection();}
}
async function continueAfterCollection(){
  const count=flow.waitingCount;flow.waitingCount=null;
  await refreshSummary();if(count&&state.summary?.remaining)await performDraw(count);
}
$('collect-now').addEventListener('click',()=>{flow.waitingCount=null;prepareCollection(true);});
$('use-existing').addEventListener('click',async()=>{
  flow.skip=true;const count=flow.waitingCount;flow.waitingCount=null;
  renderCollection({fresh:flow.ready,job:flow.collectionJob});
  if(!flow.collecting&&count){await refreshSummary();performDraw(count);}
});
function activateView(){
  const view=['warehouse','lab'].includes(location.hash.slice(1))?location.hash.slice(1):'discover';flow.view=view;
  $('discover-view').hidden=view!=='discover';$('warehouse-view').hidden=view!=='warehouse';$('lab-view').hidden=view!=='lab';
  document.querySelectorAll('.main-nav a').forEach(a=>{
    const matches=(view==='discover'&&a.getAttribute('href')==='/discover')||a.getAttribute('href')==='/discover#'+view;
    a.classList.toggle('active',matches);if(matches)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
  });
  if(view==='warehouse')loadWarehouse(flow.owned.page||1);
  if(view==='lab'){renderSelection();loadHistory();}
  window.scrollTo(0,0);
}
window.addEventListener('hashchange',activateView);
function warehouseOptions(page){return {q:$('warehouse-query').value.trim(),tier:$('warehouse-tier').value,
  status:$('warehouse-status').value,favorite:$('warehouse-favorite').checked?'1':'0',page};}
async function loadWarehouse(page=1){
  const version=++warehouseVersion;$('warehouse-message').textContent=T.warehouse_loading;
  try{
    const result=await api('/api/inventory?'+new URLSearchParams(warehouseOptions(page)));if(version!==warehouseVersion)return;
    flow.owned=result;flow.workspace=result.workspace;
    if(!flow.draftLoaded){flow.draftLoaded=true;await restoreDraft();if(version!==warehouseVersion)return;}
    $('owned-total').textContent=result.stats.total;$('owned-favorites').textContent=result.stats.favorites;$('owned-queue').textContent=result.stats.to_read;
    $('warehouse-grid').replaceChildren(...result.cards.map(ownedCard));
    $('warehouse-message').textContent=result.cards.length?'':T.warehouse_empty;
    $('warehouse-page').textContent=formatted(T.warehouse_page,result);
    $('warehouse-prev').disabled=result.page<=1;$('warehouse-next').disabled=result.page>=result.pages;
  }catch(_){if(version===warehouseVersion)$('warehouse-message').textContent=T.load_failed;}
}
function ownedCard(card,index){
  const wrapper=node('article','research-card owned-card');wrapper.id='owned-card-'+card.id;wrapper.dataset.tier=card.rarity;wrapper.style.setProperty('--i',Math.min(index,4));
  wrapper.append(front(card));
  const meta=node('div','owned-meta',T.first_drawn+' '+card.first_drawn.slice(0,10)+' · '+formatted(T.drawn_count,{count:card.draw_count}));
  const select=actionButton(flow.selected.has(card.id)?'✓ '+T.selected_card:'+ '+T.select_card,()=>toggleSelection(card),'select-combo');
  select.dataset.select=String(card.id);select.setAttribute('aria-pressed',String(flow.selected.has(card.id)));
  wrapper.append(meta,select);return wrapper;
}
$('warehouse-filters').addEventListener('submit',event=>{event.preventDefault();loadWarehouse(1);});
$('warehouse-prev').addEventListener('click',()=>loadWarehouse(flow.owned.page-1));
$('warehouse-next').addEventListener('click',()=>loadWarehouse(flow.owned.page+1));
function toggleSelection(card){
  if(flow.selected.has(card.id))flow.selected.delete(card.id);
  else{if(flow.selected.size>=6){message(T.selection_full);return;}flow.selected.set(card.id,card);}
  saveDraft();renderSelection();
}
function saveDraft(){
  if(!flow.workspace)return;
  try{localStorage.setItem('paper-orbit-combo-'+flow.workspace,JSON.stringify({ids:[...flow.selected.keys()],question:$('research-question').value}));}catch(_){}
}
async function restoreDraft(){
  try{
    const draft=JSON.parse(localStorage.getItem('paper-orbit-combo-'+flow.workspace)||'{}');
    if(typeof draft.question==='string')$('research-question').value=draft.question.slice(0,2000);
    if(Array.isArray(draft.ids)&&draft.ids.length){const result=await api('/api/inventory/selection?ids='+encodeURIComponent(draft.ids.slice(0,6).join(',')));flow.selected=new Map(result.cards.map(c=>[c.id,c]));}
  }catch(_){}
  renderSelection();
}
$('research-question').addEventListener('input',saveDraft);
function renderSelection(){
  $('selected-count').textContent=flow.selected.size;$('lab-selected-count').textContent=flow.selected.size+' / 6';
  $('selected-cards').replaceChildren();
  if(!flow.selected.size)$('selected-cards').append(node('p','composer-empty',T.no_selection));
  flow.selected.forEach(card=>{
    const row=node('div','selected-row');row.dataset.tier=card.rarity;
    row.append(node('b','selected-tier',card.rarity==='UNRATED'?'—':card.rarity),node('span','',card.title));
    const remove=actionButton('×',()=>toggleSelection(card),'icon-button');remove.setAttribute('aria-label',T.remove_card+' '+card.title);row.append(remove);$('selected-cards').append(row);
  });
  document.querySelectorAll('[data-select]').forEach(button=>{const selected=flow.selected.has(Number(button.dataset.select));button.textContent=selected?'✓ '+T.selected_card:'+ '+T.select_card;button.setAttribute('aria-pressed',String(selected));});
  $('generate-ideas').disabled=flow.ideaRunning||flow.selected.size<2;
  if(!flow.ideaRunning)$('generation-state').textContent=flow.selected.size<2?T.select_minimum:T.ready_generate;
}
async function startIdeas(){
  if(flow.ideaRunning||flow.selected.size<2)return;
  const payload={paper_ids:[...flow.selected.keys()].join(','),question:$('research-question').value.trim()};
  if(!flow.ideaRequest||flow.ideaRequest.paper_ids!==payload.paper_ids||flow.ideaRequest.question!==payload.question)
    flow.ideaRequest={...payload,request_id:crypto.randomUUID()};
  flow.ideaRunning=true;$('generate-ideas').disabled=true;$('generation-state').textContent=T.generating;saveDraft();
  try{const result=await api('/api/ideas',flow.ideaRequest);observeIdea(result.job);loadHistory();}
  catch(error){flow.ideaRunning=false;renderSelection();$('generation-state').textContent=error.message.startsWith('HTTP')?T.generation_failed:error.message;message($('generation-state').textContent);}
}
$('generate-ideas').addEventListener('click',startIdeas);
function ideaFailure(job){
  let code=job?.result?.error_code;
  if(!code&&job?.error?.includes('JSONDecodeError'))code='invalid_json';
  if(job?.status==='interrupted')code='interrupted';
  return (T['error_'+code]||T.generation_failed)+' '+T.combo_retained;
}
function showIdeaFailure(job){
  const detail=ideaFailure(job);$('generation-state').textContent=detail;message(detail);
}
function observeIdea(job){
  flow.ideaJob=job;clearTimeout(ideaTimer);
  if(job.status==='running'){
    flow.ideaRunning=true;$('generate-ideas').disabled=true;$('generation-state').textContent=T.generating;
    ideaTimer=setTimeout(async()=>{try{const result=await api('/api/task?id='+encodeURIComponent(job.id));observeIdea(result.job);}catch(_){ideaTimer=setTimeout(()=>observeIdea(job),2000);}},1200);
  }else{
    flow.ideaRunning=false;flow.ideaRequest=null;renderSelection();
    if(job.status==='succeeded'){showIdea(job);$('generation-state').textContent=T.generation_finished;message(T.generation_finished);}
    else{showIdeaFailure(job);}
    loadHistory(false);
  }
}
async function loadHistory(resume=true){
  try{
    const result=await api('/api/ideas/history');flow.history=result.jobs;$('idea-history-list').replaceChildren();
    if(!result.jobs.length)$('idea-history-list').append(node('p','composer-empty',T.history_empty));
    result.jobs.forEach(job=>{
      const item=actionButton('',()=>{if(job.status==='succeeded')showIdea(job);else if(job.status==='running')observeIdea(job);else showIdeaFailure(job);},'history-item');
      item.append(node('strong','',job.result.title||job.options.question||T.combination_deck),
        node('span','',new Date(job.started*1000).toLocaleString()+' · '+(job.status==='running'?T.task_running:job.status==='succeeded'?T.task_success:T.task_failed)));
      $('idea-history-list').append(item);
    });
    const active=result.jobs.find(j=>j.status==='running');
    if(resume&&active&&(!flow.ideaJob||flow.ideaJob.id!==active.id))observeIdea(active);
    if(!flow.activeResult){const done=result.jobs.find(j=>j.status==='succeeded');if(done)showIdea(done);}
  }catch(_){$('idea-history-list').textContent=T.load_failed;}
}
$('refresh-ideas').addEventListener('click',()=>loadHistory());
function showIdea(job){
  flow.activeResult=job;const result=job.result;const root=$('idea-result');root.hidden=false;root.replaceChildren();
  root.append(node('p','eyebrow',T.hypothesis_label),node('h2','',result.title),node('p','idea-disclaimer',T.novelty_pending));
  const byId=new Map(result.sources.map((s,i)=>[s.paper_id,{...s,index:i+1}]));
  result.ideas.forEach((idea,index)=>{
    const section=node('article','generated-idea');section.append(node('h3','',String(index+1).padStart(2,'0')+' / '+idea.title));
    for(const [key,label] of [['question','idea_question'],['hypothesis','idea_hypothesis'],['combination','idea_combination'],['experiment','idea_experiment'],['evaluation','idea_evaluation'],['risks','idea_risks'],['novelty_checks','idea_novelty']]){
      section.append(node('h4','',T[label]),node('p','',idea[key]));
    }
    section.append(node('h4','',T.idea_evidence));
    idea.evidence.forEach(entry=>{
      const source=byId.get(entry.paper_id);const quote=node('blockquote','source-evidence');
      quote.append(node('strong','','['+source.index+'] '+source.title),node('p','',entry.quote),node('small','',entry.supports));section.append(quote);
    });root.append(section);
  });
  root.append(node('h3','',T.idea_sources));
  result.sources.forEach((source,index)=>{
    const row=node('p','idea-source');const link=node('a','',String(index+1)+'. '+source.title);
    link.href='/?q='+encodeURIComponent(source.doi||source.title)+'#paper-'+source.paper_id;row.append(link);if(source.doi)row.append(node('small','',' DOI: '+source.doi));root.append(row);
  });
  const download=actionButton(T.idea_export,()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const link=node('a');link.href=url;link.download='paper-orbit-ideas-'+job.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  },'small-button');root.append(download);
}
function syncOwnedCard(card){
  if($('paper-dialog').open&&$('paper-dialog').dataset.paper===String(card.id))fillDialog(card);
  flow.owned.cards=flow.owned.cards.map(old=>old.id===card.id?{...old,...card}:old);
  if(flow.selected.has(card.id)){flow.selected.set(card.id,card);renderSelection();}
  const wrapper=$('owned-card-'+card.id);
  if(wrapper){const old=wrapper.querySelector('.card-front');const replacement=front(card);replacement.style.animation='none';old.replaceWith(replacement);}
}
activateView();loadCollection();loadWarehouse();loadHistory();