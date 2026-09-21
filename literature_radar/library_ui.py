"""Presentation helpers for the searchable reading library (no database writes)."""
from __future__ import annotations

import json
from html import escape
from urllib.parse import parse_qs, urlencode, urlparse


TEXTS = {
    "zh-CN": {
        "source_filter": "数据来源", "sort": "排序", "page_size": "每页数量",
        "recommended": "收藏与评分优先", "published": "发表时间最新", "added": "最近入库",
        "score_order": "评分最高", "title_order": "标题 A–Z", "reset": "清除筛选",
        "results": "共 {total} 篇 · 显示 {start}–{end} 篇 · 第 {page}/{pages} 页",
        "previous": "上一页", "next": "下一页", "pagination": "文献分页",
        "details": "展开摘要与阅读解析", "abstract": "原始摘要", "detailed_summary": "详细总结",
        "method_clues": "方法与模型", "data_task_clues": "数据与任务", "method_flow": "方法流程",
        "follow_up_prompts": "精读问题", "evaluation": "阅读评价", "why_read": "为什么值得读",
        "no_details": "暂无摘要或详细解析，可通过原文链接继续阅读。",
        "saving": "保存中…", "saved": "已保存", "dirty": "有未保存的修改",
        "failed": "保存失败，内容已保留，请重试。",
        "refresh": "分析已完成；保存笔记后刷新，即可查看新文献。",
        "search_hint": "支持标题、作者、DOI、摘要、标签和笔记；多个词以空格分隔。",
    },
    "en": {
        "source_filter": "Source", "sort": "Sort", "page_size": "Per page",
        "recommended": "Favorites & score", "published": "Newest published", "added": "Recently added",
        "score_order": "Highest score", "title_order": "Title A–Z", "reset": "Clear filters",
        "results": "{total} papers · Showing {start}–{end} · Page {page}/{pages}",
        "previous": "Previous", "next": "Next", "pagination": "Library pages",
        "details": "Abstract & reading analysis", "abstract": "Original abstract", "detailed_summary": "Detailed summary",
        "method_clues": "Methods & models", "data_task_clues": "Data & tasks", "method_flow": "Method workflow",
        "follow_up_prompts": "Reading questions", "evaluation": "Reading evaluation", "why_read": "Why read",
        "no_details": "No abstract or detailed analysis yet. Continue via the source link.",
        "saving": "Saving…", "saved": "Saved", "dirty": "Unsaved changes",
        "failed": "Save failed. Your edits are still here; please retry.",
        "refresh": "Analysis finished. Save your notes, then refresh to see new papers.",
        "search_hint": "Search titles, authors, DOIs, abstracts, tags and notes; separate words with spaces.",
    },
}


def library_texts(lang: str) -> dict[str, str]:
    return TEXTS["zh-CN" if lang == "zh-CN" else "en"]


def safe_source_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        if parsed.scheme in {"https", "http"} and parsed.netloc:
            return value
    except ValueError:
        pass
    return "#"


def render_pagination(total: int, page: int, page_size: int, query: str, lang: str) -> str:
    t = library_texts(lang)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size + 1 if total else 0
    summary = t["results"].format(total=total, start=start, end=min(page * page_size, total), page=page, pages=pages)
    params = parse_qs(query)

    def link(target: int, label: str) -> str:
        if target < 1 or target > pages:
            return f'<span class="muted" aria-disabled="true">{label}</span>'
        params["page"] = [str(target)]
        href = "/?" + urlencode(params, doseq=True) + "#library"
        return f'<a class="button ghost" href="{escape(href)}">{label}</a>'

    return (f'<nav class="library-navigation" aria-label="{t["pagination"]}">'
            f'<span class="muted">{summary}</span><div class="library-actions">'
            f'{link(page - 1, t["previous"])}{link(page + 1, t["next"])}</div></nav>')


def render_details(row, analysis: dict, lang: str) -> str:
    t = library_texts(lang)
    blocks = []
    for key in ("abstract", "detailed_summary", "method_clues", "data_task_clues",
                "method_flow", "follow_up_prompts", "evaluation", "why_read"):
        value = row["abstract"] if key == "abstract" else analysis.get(key)
        if not value:
            continue
        if isinstance(value, list):
            tag = "ol" if key == "method_flow" else "ul"
            body = f'<{tag}>' + "".join(f'<li>{escape(str(item))}</li>' for item in value) + f'</{tag}>'
        else:
            body = f'<p class="reading-text">{escape(str(value))}</p>'
        blocks.append(f'<section><h3>{t[key]}</h3>{body}</section>')
    if not blocks:
        blocks.append(f'<p class="muted">{t["no_details"]}</p>')
    return (f'<details class="reading-details"><summary>{t["details"]}</summary>'
            f'<div class="reading-content">{"".join(blocks)}</div></details>')


def library_script(lang: str) -> str:
    # JSON is generated from static translations, never from paper/user content.
    return "const libraryText = " + json.dumps(library_texts(lang), ensure_ascii=True) + ";\n" + r'''
    const dirtyPaperForms = new Set();
    function hasUnsavedLibraryChanges() { return dirtyPaperForms.size > 0; }
    function showLibraryRefreshNotice() {
      document.getElementById('library-refresh-notice').hidden = false;
    }
    window.addEventListener('beforeunload', (event) => {
      if (!hasUnsavedLibraryChanges()) return;
      event.preventDefault();
      event.returnValue = '';
    });
    document.querySelectorAll('form.paper-tools').forEach((form) => {
      const feedback = form.querySelector('.save-feedback');
      const button = form.querySelector('button[type="submit"]');
      const serialize = () => new URLSearchParams(new FormData(form)).toString();
      let savedValues = serialize();
      let saving = false;
      function updateDirty() {
        if (!saving && serialize() === savedValues) {
          dirtyPaperForms.delete(form);
          feedback.textContent = '';
        } else {
          dirtyPaperForms.add(form);
          feedback.textContent = libraryText.dirty;
        }
        feedback.classList.remove('save-error');
      }
      form.addEventListener('input', updateDirty);
      form.addEventListener('change', updateDirty);
      form.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
          event.preventDefault();
          if (!button.disabled) form.requestSubmit();
        }
      });
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (button.disabled) return;
        const submittedValues = serialize();
        saving = true;
        dirtyPaperForms.add(form);
        button.disabled = true;
        feedback.classList.remove('save-error');
        feedback.textContent = libraryText.saving;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        try {
          const response = await fetch(form.action, {
            method: 'POST', headers: {'Accept': 'application/json'},
            body: new URLSearchParams(submittedValues), signal: controller.signal
          });
          if (!response.ok) throw new Error('Save rejected');
          const result = await response.json();
          if (!result.ok) throw new Error('Save rejected');
          savedValues = submittedValues;
          saving = false;
          updateDirty();
          if (!dirtyPaperForms.has(form)) feedback.textContent = libraryText.saved;
          const submitted = new URLSearchParams(submittedValues);
          form.closest('.paper').classList.toggle('favorite', submitted.get('favorite') === '1');
          if (result.stats) {
            Object.entries(result.stats).forEach(([key, value]) => {
              const counter = document.querySelector('[data-stat="' + key + '"]');
              if (counter) counter.textContent = value;
            });
          }
        } catch (_error) {
          dirtyPaperForms.add(form);
          feedback.textContent = libraryText.failed;
          feedback.classList.add('save-error');
        } finally {
          saving = false;
          clearTimeout(timeout);
          button.disabled = false;
        }
      });
    });
'''