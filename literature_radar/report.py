from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

from literature_radar.models import Paper
from literature_radar.library_ui import safe_source_url
import copy
import re


def write_markdown_report(
    papers: list[Paper],
    output_path: Path,
    config: dict,
    start_date: date,
    end_date: date,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Bioinfo Literature Radar - {end_date.isoformat()}",
        "",
        f"Window: {start_date.isoformat()} to {end_date.isoformat()}",
        f"Profile: {config['profile'].get('description', '')}",
        f"Matched papers: {len(papers)}",
        "",
    ]

    if not papers:
        lines.extend(
            [
                "No papers matched the current threshold.",
                "",
                "Try lowering `run.min_score`, increasing `run.days_back`, or broadening `sources.pubmed.query`.",
            ]
        )
    else:
        for index, paper in enumerate(papers, start=1):
            lines.extend(_paper_block(index, paper))

    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_html_report(
    papers: list[Paper],
    output_path: Path,
    config: dict,
    start_date: date,
    end_date: date,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    high_score_threshold = int(config.get("report", {}).get("high_score_threshold", 18))
    top_count = sum(1 for paper in papers if paper.analysis.score >= high_score_threshold)
    avg_score = round(sum(paper.analysis.score for paper in papers) / len(papers), 1) if papers else 0
    source_counts = _source_counts(papers)

    body = "\n".join(
        _html_paper_card(index, paper, high_score_threshold)
        for index, paper in enumerate(papers, start=1)
    )
    if not papers:
        body = """
        <section class="empty-state">
          <h2>No papers matched today</h2>
          <p>可以降低 <code>run.min_score</code>、增大 <code>run.days_back</code>，或放宽 PubMed 检索式。</p>
        </section>
        """

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bioinfo Literature Radar - {escape(end_date.isoformat())}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --panel: #ffffff;
      --ink: #18202f;
      --muted: #667085;
      --line: #d9dee8;
      --accent: #0f766e;
      --accent-soft: #dff5f1;
      --warn: #a15c07;
      --warn-soft: #fff2d8;
      --high: #b42318;
      --high-soft: #ffebe8;
      --code: #f1f5f9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.62;
    }}
    .shell {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 22px 56px;
    }}
    header {{
      padding: 24px 0 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 32px;
      line-height: 1.18;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin: 0;
      color: var(--muted);
      max-width: 920px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 20px 0 22px;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .stat strong {{
      display: block;
      font-size: 24px;
      line-height: 1.1;
      margin-bottom: 4px;
    }}
    .stat span {{ color: var(--muted); font-size: 13px; }}
    .source-line {{
      margin: 0 0 24px;
      color: var(--muted);
      font-size: 14px;
    }}
    .paper {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      margin: 16px 0;
    }}
    .paper.high {{
      border-color: #f2b8b5;
      box-shadow: 0 10px 28px rgba(180, 35, 24, 0.07);
    }}
    .paper-top {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: start;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 21px;
      line-height: 1.32;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      font-size: 14px;
    }}
    .score {{
      min-width: 82px;
      text-align: center;
      border-radius: 8px;
      padding: 10px 12px;
      background: var(--accent-soft);
      color: #075e57;
      border: 1px solid #b7e6df;
    }}
    .high .score {{
      color: var(--high);
      background: var(--high-soft);
      border-color: #f7c4bf;
    }}
    .score strong {{
      display: block;
      font-size: 28px;
      line-height: 1;
    }}
    .tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 14px 0;
    }}
    .tag {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 9px;
      color: #344054;
      background: #fbfcfe;
      font-size: 13px;
    }}
    .summary {{
      margin: 14px 0;
      font-size: 15px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    .block {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .block h3 {{
      margin: 0 0 8px;
      font-size: 15px;
      line-height: 1.3;
    }}
    .block p {{ margin: 0; color: #344054; }}
    ul, ol {{
      margin: 0;
      padding-left: 21px;
    }}
    li + li {{ margin-top: 5px; }}
    .links {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
      font-size: 14px;
    }}
    a {{ color: #0b5cab; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      background: var(--code);
      border-radius: 5px;
      padding: 1px 5px;
    }}
    .empty-state {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      margin-top: 18px;
    }}
    @media (max-width: 760px) {{
      .shell {{ padding: 18px 14px 42px; }}
      h1 {{ font-size: 25px; }}
      .stats, .grid, .paper-top {{ grid-template-columns: 1fr; }}
      .score {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <h1>Bioinfo Literature Radar</h1>
      <p class="subtitle">{escape(config['profile'].get('description', ''))}</p>
    </header>

    <section class="stats" aria-label="Report summary">
      <div class="stat"><strong>{len(papers)}</strong><span>匹配文献</span></div>
      <div class="stat"><strong>{top_count}</strong><span>高分优先读</span></div>
      <div class="stat"><strong>{avg_score}</strong><span>平均分</span></div>
      <div class="stat"><strong>{escape(start_date.isoformat())}</strong><span>起始日期</span></div>
    </section>
    <p class="source-line">窗口：{escape(start_date.isoformat())} 至 {escape(end_date.isoformat())}。来源分布：{escape(source_counts)}。</p>

    {body}
  </main>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def _paper_block(index: int, paper: Paper) -> list[str]:
    paper=copy.deepcopy(paper)
    def safe(value):
        return re.sub(r'([\\`*{}\[\]()#+!|])',r'\\\1',escape(value)).replace('\n',' ')
    for field,value in vars(paper).items():
        if isinstance(value,str):setattr(paper,field,safe(value))
        elif isinstance(value,list):setattr(paper,field,[safe(str(v)) for v in value])
    paper.url=safe_source_url(paper.url)
    for field,value in vars(paper.analysis).items():
        if isinstance(value,str):setattr(paper.analysis,field,safe(value))
        elif isinstance(value,list):setattr(paper.analysis,field,[safe(str(v)) for v in value])
    authors = ", ".join(paper.authors[:6])
    if len(paper.authors) > 6:
        authors += ", et al."
    published = paper.published.isoformat() if paper.published else "unknown date"
    tags = ", ".join(paper.analysis.tags[:12]) or "none"
    methods = ", ".join(paper.analysis.method_clues) or "not detected"
    data_tasks = ", ".join(paper.analysis.data_task_clues) or "not detected"

    return [
        f"## {index}. {paper.title}",
        "",
        f"- Score: {paper.analysis.score}",
        f"- Analysis: {paper.analysis.provider}",
        f"- Source: {paper.source}",
        f"- Published: {published}",
        f"- Journal: {paper.journal or 'N/A'}",
        f"- Authors: {authors or 'N/A'}",
        f"- DOI: {paper.doi or 'N/A'}",
        f"- Link: {paper.url}",
        f"- Tags: {tags}",
        "",
        f"**One-line summary:** {paper.analysis.summary or 'No abstract available.'}",
        "",
        f"**Detailed summary:** {paper.analysis.detailed_summary or 'N/A'}",
        "",
        f"**Method/model clues:** {methods}",
        "",
        f"**Data/task clues:** {data_tasks}",
        "",
        "**Method flow:**",
        *[f"- {item}" for item in paper.analysis.method_flow],
        "",
        "**Further prompts:**",
        *[f"- {item}" for item in paper.analysis.follow_up_prompts],
        "",
        f"**Evaluation:** {paper.analysis.evaluation or 'N/A'}",
        "",
        f"**Why read:** {paper.analysis.why_read}",
        "",
    ]


def _html_paper_card(index: int, paper: Paper, high_score_threshold: int) -> str:
    is_high = paper.analysis.score >= high_score_threshold
    authors = ", ".join(paper.authors[:8])
    if len(paper.authors) > 8:
        authors += ", et al."
    published = paper.published.isoformat() if paper.published else "unknown date"
    tags = "".join(f'<span class="tag">{escape(tag)}</span>' for tag in paper.analysis.tags[:12])
    methods = _inline_or_missing(paper.analysis.method_clues)
    data_tasks = _inline_or_missing(paper.analysis.data_task_clues)
    detailed = paper.analysis.detailed_summary if is_high else paper.analysis.summary
    card_class = "paper high" if is_high else "paper"
    high_badge = "高分重点" if is_high else "候选"

    method_flow = _html_list(paper.analysis.method_flow)
    prompts = _html_list(paper.analysis.follow_up_prompts)

    return f"""
    <article class="{card_class}">
      <div class="paper-top">
        <div>
          <h2>{index}. {escape(paper.title)}</h2>
          <div class="meta">
            {escape(paper.source)} · {escape(published)} · {escape(paper.journal or 'N/A')}<br>
            {escape(authors or 'N/A')}
          </div>
        </div>
        <div class="score" aria-label="score">
          <strong>{paper.analysis.score}</strong>
          <span>{escape(high_badge)}</span>
        </div>
      </div>

      <div class="tags">{tags or '<span class="tag">none</span>'}</div>
      <p class="summary"><strong>核心总结：</strong>{escape(paper.analysis.summary or 'No abstract available.')}</p>
      <div class="block">
        <h3>{'高分文章扩展解析' if is_high else '摘要解析'}</h3>
        <p>{escape(detailed or 'No abstract available.')}</p>
      </div>

      <div class="grid">
        <section class="block">
          <h3>方法 / 模型线索</h3>
          <p>{escape(methods)}</p>
        </section>
        <section class="block">
          <h3>数据 / 任务线索</h3>
          <p>{escape(data_tasks)}</p>
        </section>
      </div>

      <div class="grid">
        <section class="block">
          <h3>方法流程</h3>
          {method_flow}
        </section>
        <section class="block">
          <h3>进一步总结提示</h3>
          {prompts}
        </section>
      </div>

      <section class="block">
        <h3>评价</h3>
        <p>{escape(paper.analysis.evaluation or paper.analysis.why_read or 'N/A')}</p>
      </section>

      <div class="links">
        <span>Analysis: {escape(paper.analysis.provider)}</span>
        <a href="{escape(safe_source_url(paper.url))}" target="_blank" rel="noreferrer">打开原文</a>
        <span>DOI: {escape(paper.doi or 'N/A')}</span>
      </div>
    </article>
    """


def _html_list(items: list[str]) -> str:
    if not items:
        return "<p>暂无，建议查看全文方法部分。</p>"
    return "<ol>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ol>"


def _inline_or_missing(items: list[str]) -> str:
    return ", ".join(items) if items else "not detected"


def _source_counts(papers: list[Paper]) -> str:
    counts: dict[str, int] = {}
    for paper in papers:
        counts[paper.source] = counts.get(paper.source, 0) + 1
    if not counts:
        return "N/A"
    return ", ".join(f"{source}: {count}" for source, count in sorted(counts.items()))
