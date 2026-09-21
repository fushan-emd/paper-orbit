"""Shared collection pipeline for CLI and the interactive card workflow."""
from datetime import date, timedelta
from pathlib import Path
from literature_radar.analysis import analyze_paper
from literature_radar.fetchers.arxiv import fetch_arxiv
from literature_radar.fetchers.biorxiv import fetch_biorxiv
from literature_radar.fetchers.openalex import fetch_openalex
from literature_radar.fetchers.pubmed import fetch_pubmed
from literature_radar.report import write_html_report, write_markdown_report
from literature_radar.storage import PaperStore


def collect_library(config, root: Path, emit=lambda message: None, output=None):
    config={**config,'_workspace_root':str(root)}
    ai_count=0;fallback_count=0
    end = date.today()
    start = end - timedelta(days=int(config['run']['days_back']))
    maximum = int(config['run']['max_papers_per_source'])
    minimum = int(config['run']['min_score'])
    store = PaperStore(root / config['project']['database'])
    store.initialize()
    before = store.dashboard_stats()['total']
    collected = {}
    failures = []
    succeeded = 0
    refreshed = 0
    for source, fetcher in [('pubmed',fetch_pubmed),('biorxiv',fetch_biorxiv),('arxiv',fetch_arxiv),('openalex',fetch_openalex)]:
        if not config.get('sources',{}).get(source,{}).get('enabled'):
            continue
        emit(f'Fetching {source}…')
        try:
            papers = fetcher(config,start,end,maximum)
        except Exception as exc:
            failures.append(source)
            status=getattr(getattr(exc,'response',None),'status_code',None)
            reason='HTTP '+str(status) if status else 'rate limit / cooldown' if source=='openalex' and str(exc).startswith(('OpenAlex rate limited','OpenAlex cooldown')) else type(exc).__name__
            emit(f'{source}: {reason}; continuing with other sources.')
            continue
        succeeded += 1
        emit(f'{source}: {len(papers)} papers found.')
        for index,paper in enumerate(papers,1):
            emit(f'Analyze {source}: {index}/{len(papers)}')
            paper.analysis = analyze_paper(paper,config)
            if paper.analysis.provider=='deepseek':ai_count+=1
            else:fallback_count+=1
            if paper.analysis.score >= minimum:
                store.upsert_paper(paper)
                refreshed += 1
                current = collected.get(paper.identity)
                if current is None or paper.analysis.score > current.analysis.score:
                    collected[paper.identity] = paper
            emit(f'Analyze {source}: {index}/{len(papers)}')
    if not succeeded:
        raise RuntimeError('No literature source completed. Check enabled sources and network access.')
    papers = sorted(collected.values(),key=lambda p:(p.analysis.score,p.published or date.min),reverse=True)
    report_dir = root / config['project']['report_dir']
    if output:
        path = root / output
        (write_markdown_report if path.suffix.lower()=='.md' else write_html_report)(papers,path,config,start,end)
    else:
        write_html_report(papers,report_dir/f'daily_report_{end.isoformat()}.html',config,start,end)
        write_markdown_report(papers,report_dir/f'daily_report_{end.isoformat()}.md',config,start,end)
    after = store.dashboard_stats()['total']
    result = dict(added=max(0,after-before),matched=len(papers),updated=refreshed,total=after,
                  sources_ok=succeeded,sources_failed=failures,ai_scored=ai_count,rule_scored=fallback_count)
    emit(f'Collection complete: {result["added"]} new papers; {len(papers)} matches; {after} in library.')
    return result