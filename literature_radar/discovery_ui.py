"""Self-contained discovery page; assets are bundled with the desktop application."""
from html import escape
from pathlib import Path
import json
import re

ZH = {
 'lang':'zh-CN','discover':'灵感抽卡','library':'文献库','collection':'我的收藏','navigation':'主导航','theme':'切换深浅主题','settings':'设置',
 'hero_a':'让下一篇灵感，','hero_b':'为你翻开。','hero_description':'把每日文献探索，变成一次有期待的发现。抽取、翻阅、收藏，让值得精读的研究自然浮现。',
 'ai_curated':'AI 相关性评级','no_repeats':'本轮不重复','real_library':'来自你的文献库','potential':'值得深入的发现',
 'draw_controls':'文献抽卡控制','pool':'卡池','unread':'未读探索','to_read_pool':'待读重访','all_pool':'全库漫游','available':'篇可抽取',
 'search_placeholder':'输入主题、作者或 DOI，缩小探索范围','ai_only':'仅抽取已有 AI 评分的文献','single':'单抽','five':'五连抽','ten':'十连抽',
 'loading':'正在连接你的文献星图…','skip_animation':'快速揭晓','reset':'开启新一轮','rarity_rules':'等级分数与可抽数量','rarity_label':'稀有度 · AI / 30',
 'rating_rules':'评级说明','results':'本轮发现','reveal_all':'全部揭晓','save_revealed':'收藏已揭晓','empty_title':'你的下一篇好文，正在等你翻开',
 'empty_description':'选择一个卡池，试试单抽或连抽。每张卡片都连接真实文献，以及值得继续追问的问题。',
 'javascript_required':'抽卡模式需要启用 JavaScript，也可以继续使用文献库。','footer_note':'好奇心是入口，精读才是收获。','close':'关闭',
 'rules_description':'N 0–9 / R 10–17 / SR 18–23 / SSR 24–27 / UR 28–30。等级由已保存的 DeepSeek 评分决定，表示对你的研究方向的阅读优先级。新评分按以下四项相加，总分 30：',
 'relevance':'方向相关性','methods':'方法价值','evidence':'摘要证据','reusability':'可复用性',
 'rules_legacy':'已有 AI 评分直接沿用；历史记录未提供分项时不补造分项。只有规则初筛、AI 失败或无有效 AI 分数的文献标为“待评级”。评分基于标题和摘要，不代表全文质量或期刊等级。',
 'rules_draw':'卡池中的每篇文献等概率抽取，已抽文献在本轮不再出现。每次抽取不足 5 或 10 篇时返回剩余文献；不设置虚假的保底。开启新一轮只重置抽取记录，保留收藏、笔记和阅读状态。',
 'configure_ai':'配置 AI 与启动分析','pool_hint':'本轮已发现 {seen} 篇 · 不足连抽数量时，自动抽取剩余文献。',
 'no_library':'这个卡池暂无文献。可切换卡池，或到文献库运行分析。','pool_empty':'暂无符合条件的未抽文献。可取消“仅 AI 评分”、更换主题，或开启新一轮。',
 'load_failed':'文献池加载失败，请切换卡池重试。','unrated':'待评级','queued':'已在阅读队列','queue':'加入待读','reveal_progress':'已揭晓 {seen} / {total}',
 'saved_count':'收藏 {count} 篇','reveal_hint':'点击卡背逐张揭晓，或一次翻开全部。','no_abstract':'暂无摘要，展开详情查看原文。','pending_rating':'等待 AI 评分','ai_match':'DeepSeek · 阅读优先级',
 'read_details':'展开阅读','saved':'已收藏','save':'收藏','reveal_card':'揭晓文献','tap_reveal':'点击，揭晓这篇研究','last_results':'上次发现',
 'drawing':'正在展开你的文献星图…','partial_draw':'本次抽取 {count} 篇，已到达当前卡池末尾。','draw_failed':'抽取暂未完成，请重试同一抽数；已生成的结果会自动找回。',
 'unsaved':'已取消收藏。','queue_saved':'已加入阅读队列，原有笔记保持不变。','favorite_saved':'已存入你的收藏。','action_failed':'保存失败，请重试；卡片仍保留在这里。',
 'batch_saved':'已收藏 {count} 篇文献。','batch_failed':'已收藏 {count} 篇，其余保存失败，请重试。','reset_done':'新一轮已开启，收藏、笔记和阅读状态保持不变。',
 'why_read':'为什么值得读','abstract':'原始摘要','detailed_summary':'详细总结','data_tasks':'数据与任务','method_flow':'方法流程','questions':'精读问题','evaluation':'阅读建议','open_library':'到文献库写笔记','original':'打开原文',
}
EN = {
 'lang':'en','discover':'Discover','library':'Library','collection':'Saved','navigation':'Main navigation','theme':'Switch color theme','settings':'Settings',
 'hero_a':'Your next idea,','hero_b':'waiting to unfold.','hero_description':'A little curiosity. A new perspective. Draw from your research library and discover the papers worth a closer read.',
 'ai_curated':'AI reading priorities','no_repeats':'No repeats this round','real_library':'Your real library','potential':'A discovery worth exploring',
 'draw_controls':'Paper draw controls','pool':'Card pool','unread':'Unread discoveries','to_read_pool':'Reading queue','all_pool':'Whole library','available':'papers available',
 'search_placeholder':'Explore a topic, author or DOI','ai_only':'Only papers with an existing AI score','single':'Single','five':'Draw five','ten':'Draw ten',
 'loading':'Connecting your research constellation…','skip_animation':'Quick reveal','reset':'New round','rarity_rules':'Rarity scores and available counts','rarity_label':'RARITY · AI / 30',
 'rating_rules':'How ratings work','results':'Your discoveries','reveal_all':'Reveal all','save_revealed':'Save revealed','empty_title':'Your next great read is waiting',
 'empty_description':'Choose a pool and draw one, five or ten. Every card connects to a real paper and questions worth asking.',
 'javascript_required':'Discovery mode requires JavaScript. You can also use the library.','footer_note':'Start with curiosity. Stay for the science.','close':'Close',
 'rules_description':'N 0–9 / R 10–17 / SR 18–23 / SSR 24–27 / UR 28–30. Rarity reflects reading priority for your research interests, using stored DeepSeek scores. New scores sum four dimensions to a total of 30:',
 'relevance':'Topic relevance','methods':'Method value','evidence':'Abstract evidence','reusability':'Reusability',
 'rules_legacy':'Existing AI scores remain valid; missing dimension scores are never invented. Heuristic-only, failed or invalid AI scores are marked Unrated. Ratings use titles and abstracts, not full-paper or journal quality.',
 'rules_draw':'Every eligible paper has the same chance. No repeats within a round; short draws return the remaining papers. There are no artificial guarantees. A new round resets discovery history only, preserving notes, favorites and reading status.',
 'configure_ai':'Configure AI & run analysis','pool_hint':'{seen} discovered this round · Short draws return the remaining papers.',
 'no_library':'No papers in this pool. Try another pool or run an analysis in the library.','pool_empty':'No undrawn matches. Include unrated papers, change your topic, or start a new round.',
 'load_failed':'Could not load the pool. Choose a pool to retry.','unrated':'Unrated','queued':'In reading queue','queue':'Read later','reveal_progress':'Revealed {seen} / {total}',
 'saved_count':'{count} saved','reveal_hint':'Tap a card to reveal, or turn them all at once.','no_abstract':'No abstract available. Open the paper for more.','pending_rating':'Awaiting AI rating','ai_match':'DeepSeek · Reading priority',
 'read_details':'Read more','saved':'Saved','save':'Save','reveal_card':'Reveal paper','tap_reveal':'Tap to discover','last_results':'Last discoveries',
 'drawing':'Unfolding your research constellation…','partial_draw':'Drew {count} papers; this pool is now exhausted.','draw_failed':'Draw not confirmed. Retry the same draw size to recover any saved result.',
 'unsaved':'Removed from saved papers.','queue_saved':'Added to your reading queue. Notes are preserved.','favorite_saved':'Added to saved papers.','action_failed':'Save failed. Please retry; your cards are still here.',
 'batch_saved':'Saved {count} papers.','batch_failed':'Saved {count} papers. Please retry the remaining saves.','reset_done':'New round started. Your notes and reading progress are preserved.',
 'why_read':'Why read','abstract':'Original abstract','detailed_summary':'Detailed summary','data_tasks':'Data & tasks','method_flow':'Method workflow','questions':'Reading questions','evaluation':'Reading advice','open_library':'Write notes in library','original':'Open original',
}


ZH.update({
 'warehouse':'卡牌仓库','idea_lab':'灵感工坊','prepare':'扩充牌库','collect_first':'每日首次抽卡，先发现新文献。',
 'checking_collection':'正在检查今日补库状态…','collect_now':'搜集并扩充牌库','use_existing':'本次暂用现有牌库','configure_sources':'配置来源与 AI','task_progress':'查看搜集进度',
 'collection_due':'今日尚未补库。点击抽卡后将先搜集并分析，再自动继续抽取。',
 'collection_running':'正在搜集与分析文献，完成后会自动扩充牌库。',
 'collection_done':'本次新增 {added} 篇，匹配 {matched} 篇；牌库共 {total} 篇。',
 'collection_partial':'部分来源暂时不可用，其余来源已完成。',
 'collection_failed':'搜集未完成，可重试或本次暂用现有牌库。',
 'collection_skip':'本次使用已有牌库；仍可随时手动搜集。','collection_wait':'先搜集，再抽卡…','collection_check_failed':'无法检查补库状态，请重试。',
 'warehouse_title':'每一次发现，都有归处。','warehouse_description':'抽过的卡自动入仓，收藏与阅读状态同步。新一轮抽卡不会清空这里。',
 'open_lab':'组合生成想法','owned_cards':'仓库卡牌','warehouse_search':'搜索卡牌、作者、DOI 或笔记','all_rarities':'全部等级','reading_status':'阅读状态','all_statuses':'全部阅读状态',
 'status_new':'新入库','status_reading':'精读中','status_read':'已读','status_reproduce':'可复现','status_ignore':'忽略','favorites_only':'只看收藏','filter_cards':'筛选',
 'previous_page':'上一页','next_page':'下一页','warehouse_empty':'仓库还没有匹配卡牌。先去抽卡，或调整筛选条件。','warehouse_loading':'正在打开仓库…',
 'warehouse_page':'共 {total} 张 · 第 {page}/{pages} 页','first_drawn':'首次入仓','drawn_count':'累计抽到 {count} 次','select_card':'加入组合','selected_card':'已加入组合','selection_full':'最多组合 6 张卡，请先移除一张。',
 'lab_title':'把不同的研究，连成新问题。','lab_description':'从仓库选择 2–6 张卡，让 AI 将方法、数据与研究问题组合成可检验的假设。',
 'choose_cards':'去仓库选卡','combination_deck':'你的组合卡组','research_question':'研究方向与限制（可选）','question_placeholder':'例如：将空间组学与细胞扰动模型结合；只有公开数据，优先考虑可在单张 GPU 上完成的实验。',
 'generate_ideas':'生成科研新想法','select_minimum':'至少选择 2 张不同文献卡','ready_generate':'卡组已就绪，生成结果将自动存档。','generating':'AI 正在组合文献并核对依据…',
 'generation_note':'使用已配置的 DeepSeek，发送所选文献标题、摘要和本次研究问题；不发送个人笔记。输出为待验证假设，新颖性仍需后续检索。',
 'idea_history':'想法档案','refresh_history':'刷新','history_empty':'生成的想法会保存在这里。','remove_card':'移除','no_selection':'还没有组合卡。到仓库挑选不同方法或主题的文献。',
 'generation_failed':'生成失败，卡组已保留。请检查 AI 配置或网络后重试。','generation_finished':'想法已生成并保存。','task_running':'进行中','task_failed':'未完成','task_success':'已完成',
 'hypothesis_label':'AI 生成 · 待验证假设','novelty_pending':'尚未进行新颖性检索','idea_question':'研究问题','idea_hypothesis':'可检验假设','idea_combination':'组合逻辑','idea_experiment':'最小实验与对照','idea_evaluation':'评价指标与证伪条件','idea_risks':'风险与证据缺口','idea_novelty':'后续新颖性核查','idea_evidence':'文献依据（原文片段）','idea_sources':'本次使用的文献','idea_export':'下载想法 JSON','history_loading':'正在读取想法档案…',
})
EN.update({
 'warehouse':'Warehouse','idea_lab':'Idea lab','prepare':'Grow your library','collect_first':'Fresh papers before your first draw of the day.',
 'checking_collection':'Checking today’s collection…','collect_now':'Collect new papers','use_existing':'Use existing library this time','configure_sources':'Sources & AI settings','task_progress':'Collection progress',
 'collection_due':'No collection today yet. Your next draw will collect and analyze papers first, then continue automatically.',
 'collection_running':'Collecting and analyzing papers. Your pool will update when ready.',
 'collection_done':'Added {added} papers, matched {matched}; {total} papers in the library.',
 'collection_partial':'Some sources were unavailable; the remaining sources completed.',
 'collection_failed':'Collection did not finish. Retry or use the existing library this time.',
 'collection_skip':'Using the existing library this time. You can still collect manually.','collection_wait':'Collecting before the draw…','collection_check_failed':'Unable to check collection. Please retry.',
 'warehouse_title':'A home for every discovery.','warehouse_description':'Every drawn card is kept here with synced favorites and reading status, even after a new round.',
 'open_lab':'Combine into ideas','owned_cards':'Owned cards','warehouse_search':'Search cards, authors, DOIs or notes','all_rarities':'All rarities','reading_status':'Reading status','all_statuses':'All reading states',
 'status_new':'New','status_reading':'Reading','status_read':'Read','status_reproduce':'Reproduce','status_ignore':'Ignore','favorites_only':'Favorites only','filter_cards':'Filter',
 'previous_page':'Previous','next_page':'Next','warehouse_empty':'No matching cards. Draw some papers or adjust your filters.','warehouse_loading':'Opening the warehouse…',
 'warehouse_page':'{total} cards · Page {page}/{pages}','first_drawn':'First acquired','drawn_count':'Drawn {count} times','select_card':'Add to combo','selected_card':'In combo','selection_full':'Up to 6 cards per combo. Remove one first.',
 'lab_title':'Connect papers. Create questions.','lab_description':'Choose 2–6 owned cards to combine methods, data and research questions into testable hypotheses.',
 'choose_cards':'Choose owned cards','combination_deck':'Your combination','research_question':'Research direction & constraints (optional)','question_placeholder':'For example: combine spatial omics and perturbation models, using public data and a single GPU.',
 'generate_ideas':'Generate research ideas','select_minimum':'Select at least 2 different papers','ready_generate':'Ready to generate. Results will be saved automatically.','generating':'Combining papers and checking source evidence…',
 'generation_note':'Uses your configured DeepSeek model with selected titles, abstracts and this question. Personal notes are not sent. Outputs are hypotheses; novelty requires a later search.',
 'idea_history':'Idea archive','refresh_history':'Refresh','history_empty':'Generated ideas will be saved here.','remove_card':'Remove','no_selection':'Your combo is empty. Choose papers with complementary methods or topics in the warehouse.',
 'generation_failed':'Generation failed. Your combo is retained. Check AI settings or network and retry.','generation_finished':'Ideas generated and saved.','task_running':'Running','task_failed':'Incomplete','task_success':'Completed',
 'hypothesis_label':'AI generated · Hypotheses to validate','novelty_pending':'Novelty has not been checked','idea_question':'Research question','idea_hypothesis':'Testable hypothesis','idea_combination':'How the papers connect','idea_experiment':'Minimal experiment & controls','idea_evaluation':'Metrics & falsification','idea_risks':'Risks & evidence gaps','idea_novelty':'Novelty checks still needed','idea_evidence':'Source evidence (exact excerpts)','idea_sources':'Selected source papers','idea_export':'Download idea JSON','history_loading':'Loading idea archive…',
})


ZH.update({
 'combo_retained':'卡组已保留，可重试。',
 'error_invalid_json':'AI 返回的内容不是完整、可解析的 JSON，请重新生成。',
 'error_output_truncated':'AI 回复达到输出上限而被截断。请减少选卡或缩短研究要求后重试。',
 'error_empty_response':'AI 没有返回正文，请重试或检查所选模型。',
 'error_invalid_envelope':'AI 服务返回了无法识别的响应，请检查接口地址或稍后重试。',
 'error_invalid_schema':'AI 回复缺少必要字段，请重新生成。',
 'error_evidence_mismatch':'AI 引用未能匹配所选文献原文，本次结果未采纳，请重新生成。',
 'error_content_filtered':'AI 服务未完成这次请求，请调整研究问题后重试。',
 'error_authentication':'AI 服务拒绝了身份验证，请检查 API key 与访问权限。',
 'error_balance':'AI 账户余额不足，请检查服务商账户。',
 'error_model_unavailable':'模型或接口不存在，请检查模型名称与接口地址。',
 'error_rate_limit':'AI 请求过于频繁或配额已用尽，请稍后重试或检查账户额度。',
 'error_timeout':'等待 AI 回复超时，请稍后重试。',
 'error_connection':'无法连接 AI 服务，请检查网络或代理。',
 'error_provider_error':'AI 服务返回错误，请稍后重试。',
 'error_interrupted':'上次生成因软件退出或任务中断未完成，请重试。',
 'rare_discovery':'高评级文献已揭晓','ultra_discovery':'发现值得深入阅读的文献',
})
EN.update({
 'combo_retained':'Your combo is retained; you can retry.',
 'error_invalid_json':'The AI response was not valid, complete JSON. Generate again.',
 'error_output_truncated':'The response hit its output limit. Try fewer cards or a shorter question.',
 'error_empty_response':'The AI returned no content. Retry or check your model.',
 'error_invalid_envelope':'Unrecognized AI service response. Check the endpoint or retry later.',
 'error_invalid_schema':'Required fields were missing from the AI response. Generate again.',
 'error_evidence_mismatch':'AI citations did not match the selected source text. The result was rejected; generate again.',
 'error_content_filtered':'The AI service did not complete the request. Revise your question.',
 'error_authentication':'Authentication failed. Check your API key and permissions.',
 'error_balance':'Insufficient AI account balance. Check your provider account.',
 'error_model_unavailable':'Model or endpoint not found. Check your settings.',
 'error_rate_limit':'Rate limit or quota reached. Retry later or check your quota.',
 'error_timeout':'The AI response timed out. Retry later.',
 'error_connection':'Cannot connect to the AI service. Check your network or proxy.',
 'error_provider_error':'The AI service returned an error. Retry later.',
 'error_interrupted':'The previous task was interrupted. Please retry.',
 'rare_discovery':'High-priority paper revealed','ultra_discovery':'A paper to explore in depth',
})


ZH.update({'error_cancelled':'任务已取消。','error_budget_limit':'今日 AI 用量达到设置上限，请查看数据与任务。'})
EN.update({'error_cancelled':'Task cancelled.','error_budget_limit':'Daily AI budget reached. Check Data & Tasks.'})

ZH.update({'preprint_notice':'预印本 · 请核对正式版本','status_unverified':'版本与撤稿状态尚未核查','abstract_scope':'评级与解析基于标题、摘要，不代表全文质量认证。'})
EN.update({'preprint_notice':'Preprint · Check published version','status_unverified':'Version / retraction status unchecked','abstract_scope':'Analysis uses titles and abstracts; not a full-paper quality certification.'})

ZH.update({'retracted_notice':'来源标记撤稿或撤稿通知，请核对原文','source_status':'来源本次未标记撤稿，仍需核对原文'})
EN.update({'retracted_notice':'Source flags a retraction / notice; verify original','source_status':'No retraction flag in this source snapshot; verify original'})

ZH.update({'collection_scoring':'AI 评分 {ai_scored} 篇，规则分析 {rule_scored} 篇。'})
EN.update({'collection_scoring':'AI scored: {ai_scored}; rule analysis: {rule_scored}.'})

ZH.update({'tutorial':'新手教程','tutorial_skip':'稍后再说','tutorial_back':'上一步','tutorial_next':'下一张'})
EN.update({'tutorial':'Getting started','tutorial_skip':'Skip for now','tutorial_back':'Back','tutorial_next':'Next card'})

def discovery_page(lang='zh-CN', show_onboarding=False):
    texts = ZH if lang == 'zh-CN' else EN
    assets = Path(__file__).with_name('assets')
    html = (assets / 'discovery.html').read_text(encoding='utf-8')
    html = html.replace('__ONBOARDING__', 'true' if show_onboarding else 'false')
    html = re.sub(r'\[\[([a-z_]+)\]\]', lambda m: escape(texts[m[1]]), html)
    return (html.replace('__CSS__', (assets/'discovery.css').read_text(encoding='utf-8'))
            .replace('__TEXTS__', json.dumps(texts, ensure_ascii=True))
            .replace('__JS__', (assets/'discovery.js').read_text(encoding='utf-8') + '\n' + (assets/'workbench.js').read_text(encoding='utf-8')))