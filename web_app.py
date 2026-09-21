from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from datetime import datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from literature_radar.config import load_config, write_config
from literature_radar.security import allowed_request, has_session, valid_token, secure_html, SESSION_TOKEN, MAX_BODY, require_loopback, validate_ai_url
from literature_radar.deepseek import deepseek_status
from literature_radar.secrets import get_secret, mask_secret, save_secret, delete_secret
from literature_radar.paths import workspace_root
from literature_radar.backup import WORKSPACE_LOCK, snapshot, restore, export_library
from literature_radar.management import page as management_page
from literature_radar.storage import LIBRARY_SORTS, PaperStore
from literature_radar.discovery import DiscoveryDeck, rarity
from literature_radar.discovery_ui import discovery_page
from literature_radar.workflows import TaskStore, collection_state, ensure_collection, JobBusyError
from literature_radar.ideation import ai_settings, source_snapshots, generate_ideas
from literature_radar.library_ui import (
    library_script, library_texts, render_details, render_pagination, safe_source_url,
)


ROOT = workspace_root()
CONFIG_PATH = ROOT / "config.toml"
LOG_DIR = ROOT / "logs"

RUN_LOG: list[str] = []
LAST_SETTINGS_ERROR: str = ""
LAST_SETTINGS_MESSAGE: str = ""


class LiteratureHandler(BaseHTTPRequestHandler):
    server_version = "PaperOrbit/0.4"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def do_GET(self) -> None:
        if not allowed_request(self):
            self.send_error(HTTPStatus.FORBIDDEN); return
        if self.path.startswith('/api/') and not has_session(self):
            self.send_error(HTTPStatus.FORBIDDEN); return
        parsed = urlparse(self.path)
        if parsed.path=='/manage':
            self._html(management_page(ROOT,current_config(),current_store()));return
        if parsed.path=='/api/export':
            payload=json.dumps(export_library(current_store()),ensure_ascii=False,indent=2).encode('utf-8')
            self.send_response(HTTPStatus.OK);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Disposition','attachment; filename="paper-orbit-library.json"')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
        if parsed.path.startswith('/policy/'):
            names={'privacy':'PRIVACY.md','license':'LICENSE','notices':'THIRD_PARTY_NOTICES.md'}
            name=names.get(parsed.path.rsplit('/',1)[-1])
            if not name:self.send_error(HTTPStatus.NOT_FOUND);return
            path=Path(__file__).parent/name
            if not path.exists():self.send_error(HTTPStatus.NOT_FOUND);return
            self._html('<html><head><meta charset="utf-8"><title>Paper Orbit</title></head><body><a href="/manage">返回</a><pre style="white-space:pre-wrap">'+escape(path.read_text(encoding='utf-8'))+'</pre></body></html>');return
        if parsed.path == "/":
            try:
                self._html(dashboard_page(parsed.query))
            except Exception as exc:
                self._html(error_page(exc))
            return
        if parsed.path == "/discover":
            self._html(discovery_page(_language(current_config()), bool(current_config().get("web", {}).get("show_onboarding", False))))
            return
        if parsed.path == "/api/discovery":
            try:
                params = parse_qs(parsed.query)
                deck = DiscoveryDeck(current_store())
                result = {"ok": True, "summary": deck.summary(**_discovery_options(params))}
                if _first(params, "latest") == "1":
                    result["batch"] = deck.latest()
                self._json(result)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception:
                self._json({"ok": False, "error": "Unable to load discovery pool"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path in {"/api/collection", "/api/task", "/api/inventory", "/api/inventory/selection", "/api/ideas/history"}:
            try:
                config=current_config(); store=current_store(config); params=parse_qs(parsed.query)
                tasks=TaskStore(store)
                if parsed.path == "/api/collection":
                    result=collection_state(tasks,config)
                elif parsed.path == "/api/task":
                    result={"job":tasks.get(_first(params,"id"))}
                elif parsed.path == "/api/ideas/history":
                    result={"jobs":tasks.history('ideas')}
                elif parsed.path == "/api/inventory/selection":
                    ids=[int(value) for value in _first(params,"ids").split(',') if value]
                    result={"cards":DiscoveryDeck(store).owned_cards(ids) if ids else []}
                else:
                    result=DiscoveryDeck(store).inventory(query=_first(params,"q"),favorite=_first(params,"favorite")=="1",
                        tier=_first(params,"tier"),status=_first(params,"status"),page=int(_first(params,"page","1")))
                    result['workspace']=hashlib.sha256(str(store.db_path.resolve()).encode()).hexdigest()[:16]
                self._json({"ok":True,**result})
            except (ValueError,LookupError) as exc:
                self._json({"ok":False,"error":str(exc)},HTTPStatus.NOT_FOUND if isinstance(exc,LookupError) else HTTPStatus.BAD_REQUEST)
            except Exception:
                self._json({"ok":False,"error":"Unable to load workspace"},HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/run-status":
            self._json(run_status())
            return
        if parsed.path.startswith("/reports/"):
            self._serve_report(parsed.path.removeprefix("/reports/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        with WORKSPACE_LOCK:
            self._post()

    def _post(self) -> None:
        if not allowed_request(self) or not has_session(self):
            self.send_error(HTTPStatus.FORBIDDEN); return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<0 or length>MAX_BODY:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE); return
            if self.headers.get('Transfer-Encoding'):
                self.send_error(HTTPStatus.BAD_REQUEST); return
            content_type=self.headers.get('Content-Type','').split(';')[0]
            if content_type and content_type!='application/x-www-form-urlencoded':
                self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE); return
            body=self.rfile.read(length).decode('utf-8')
            self._parsed_form=parse_qs(body,keep_blank_values=True)
            if not valid_token(self.headers.get('X-Orbit-Token')) and not valid_token(_first(self._parsed_form,'_csrf')):
                self.send_error(HTTPStatus.FORBIDDEN); return
        except (ValueError,UnicodeError):
            self.send_error(HTTPStatus.BAD_REQUEST); return
        parsed = urlparse(self.path)
        if parsed.path.startswith('/manage/'):
            params=self._form()
            try:
                store=current_store()
                if parsed.path=='/manage/backup':
                    result='备份已创建：'+snapshot(store.db_path,ROOT/'backups').name
                elif parsed.path=='/manage/restore':
                    if _first(params,'confirmation')!='RESTORE':raise ValueError('请输入 RESTORE 确认')
                    previous=restore(store.db_path,ROOT/'backups',_first(params,'backup'))
                    store.initialize();result='恢复完成。恢复前备份：'+previous
                elif parsed.path=='/manage/cancel':
                    TaskStore(store).cancel(_first(params,'id'));result='取消已请求。当前网络请求完成后生效。'
                else:self.send_error(HTTPStatus.NOT_FOUND);return
            except (ValueError,LookupError) as exc:result=str(exc)
            except Exception:result='操作未完成，请检查磁盘空间、文件权限或备份。'
            self._html(management_page(ROOT,current_config(),current_store(),result));return
        if parsed.path in {"/api/collection/ensure", "/api/ideas"}:
            try:
                params=self._form(); config=copy.deepcopy(current_config()); config["_workspace_root"]=str(ROOT); store=current_store(config); tasks=TaskStore(store)
                if parsed.path == "/api/collection/ensure":
                    result=ensure_collection(tasks,config,ROOT,force=_first(params,"force")=="1",request_id=_first(params,"request_id") or None)
                else:
                    ids=[int(value) for value in _first(params,"paper_ids").split(',') if value]
                    if not 2<=len(ids)<=6:raise ValueError('Select 2 to 6 owned cards')
                    question=_first(params,"question").strip()
                    if len(question)>2000:raise ValueError('Research question is too long')
                    sources=source_snapshots(DiscoveryDeck(store).owned_cards(ids))
                    settings,_=ai_settings(config)
                    options={"paper_ids":ids,"question":question,"model":settings.get('model','deepseek-v4-flash')}
                    result={"job":tasks.start('ideas',options,lambda emit:generate_ideas(config,sources,question,emit),
                                             request_id=_first(params,"request_id") or None)}
                self._json({"ok":True,**result})
            except JobBusyError as exc:
                self._json({"ok":False,"error":str(exc)},HTTPStatus.CONFLICT)
            except (ValueError,LookupError) as exc:
                self._json({"ok":False,"error":str(exc)},HTTPStatus.BAD_REQUEST)
            except Exception:
                self._json({"ok":False,"error":"Unable to start task"},HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path in {"/api/discovery/draw", "/api/discovery/action", "/api/discovery/reset"}:
            try:
                params = self._form()
                deck = DiscoveryDeck(current_store())
                if parsed.path.endswith("/action"):
                    paper_id = int(_first(params, "paper_id", "0"))
                    if paper_id <= 0:
                        raise ValueError("Invalid paper ID")
                    self._json({"ok": True, "card": deck.act(paper_id, _first(params, "action"))})
                else:
                    options = _discovery_options(params)
                    result = {"ok": True}
                    if parsed.path.endswith("/draw"):
                        result["batch"] = deck.draw(int(_first(params, "count", "0")),
                                                   _first(params, "request_id"), **options)
                    else:
                        deck.reset()
                    result["summary"] = deck.summary(**options)
                    self._json(result)
            except (ValueError, LookupError) as exc:
                self._json({"ok": False, "error": str(exc)},
                           HTTPStatus.NOT_FOUND if isinstance(exc, LookupError) else HTTPStatus.BAD_REQUEST)
            except Exception:
                self._json({"ok": False, "error": "Unable to update discovery"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/run":
            params = self._form()
            start_run(
                days=_optional_int(_first(params, "days")),
                max_per_source=_optional_int(_first(params, "max_per_source")),
                min_score=_optional_int(_first(params, "min_score")),
            )
            self._redirect("/")
            return
        if parsed.path == "/settings":
            params = self._form()
            try:
                save_settings(params)
            except Exception as exc:
                set_settings_feedback(error=f"{type(exc).__name__}: {exc}")
            else:
                set_settings_feedback(message="Settings saved.")
            self._redirect("/?settings=1")
            return
        if parsed.path == "/language":
            params = self._form()
            save_language(_first(params, "language", "zh-CN"))
            self._redirect("/")
            return
        if parsed.path == "/onboarding/progress":
            params = self._form()
            try:
                step = int(_first(params, 'step', '-1'))
                active = _first(params, 'active')
                if step not in range(8) or active not in {'0', '1'}:
                    raise ValueError('Invalid tutorial state')
                config = current_config()
                web = config.setdefault('web', {})
                previous = dict(web)
                web.update(tutorial_step=step, show_onboarding=active == '1')
                try:
                    write_config(config, CONFIG_PATH)
                except Exception:
                    web.clear(); web.update(previous)
                    raise
            except ValueError:
                self._json({'ok': False, 'error': 'invalid_tutorial_state'}, HTTPStatus.BAD_REQUEST)
            except OSError:
                self._json({'ok': False, 'error': 'tutorial_save_failed'}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                self._json({'ok': True})
            return
        if parsed.path == "/onboarding/dismiss":
            dismiss_onboarding()
            self._redirect("/")
            return
        if parsed.path == "/paper/update":
            wants_json = "application/json" in self.headers.get("Accept", "")
            try:
                params = self._form()
                paper_id = int(_first(params, "paper_id", "0"))
                if paper_id <= 0:
                    raise ValueError("Invalid paper ID")
                if not {"favorite", "read_status", "user_note"}.issubset(params):
                    raise ValueError("Missing paper fields")
                favorite = _first(params, "favorite")
                if favorite not in {"0", "1"}:
                    raise ValueError("Invalid favorite value")
                store = current_store()
                store.update_user_fields(
                    paper_id,
                    favorite=favorite == "1",
                    read_status=_first(params, "read_status"),
                    user_note=_first(params, "user_note"),
                )
            except (ValueError, LookupError) as exc:
                status_code = HTTPStatus.NOT_FOUND if isinstance(exc, LookupError) else HTTPStatus.BAD_REQUEST
                if wants_json:
                    self._json({"ok": False, "error": str(exc)}, status_code)
                else:
                    self.send_error(status_code, str(exc))
            except Exception:
                self._json({"ok": False, "error": "Unable to save paper"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                if wants_json:
                    self._json({"ok": True, "stats": store.dashboard_stats()})
                else:
                    self._redirect("/?" + urlencode(parse_qs(_first(params, "return_query")), doseq=True) + "#library")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        print(f"[{timestamp}] web {self.address_string()} {getattr(self,'command','')} {urlparse(getattr(self,'path','')).path}", flush=True)

    def _form(self) -> dict[str, list[str]]:
        return self._parsed_form

    def _html(self, content: str) -> None:
        if urlparse(self.path).path in {'/', '/discover', '/manage'} or urlparse(self.path).path.startswith('/manage/'):
            from literature_radar.onboarding import inject
            from literature_radar.navigation import inject as navigation
            config = current_config()
            content = navigation(content, self.path, _language(config))
            content = inject(content, config)
        payload = secure_html(content).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Set-Cookie", f"orbit_session={SESSION_TOKEN}; HttpOnly; SameSite=Strict; Path=/")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, target: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", target)
        self.end_headers()

    def _serve_report(self, name: str) -> None:
        config = current_config()
        report_dir = ROOT / config["project"]["report_dir"]
        safe_name = Path(unquote(name)).name
        path = report_dir / safe_name
        if not path.exists() or path.suffix.lower() not in {".html", ".md"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        is_html = path.suffix.lower() == ".html"
        content_type = "text/html; charset=utf-8" if is_html else "text/markdown; charset=utf-8"
        content = path.read_text(encoding="utf-8", errors="replace")
        if is_html:
            content = _add_report_navigation(content, _language(config))
        payload = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _add_report_navigation(content: str, lang: str) -> str:
    label = "\u8fd4\u56de\u5de5\u4f5c\u53f0" if lang == "zh-CN" else "Back to workspace"
    navigation = f"""
<div style="position:sticky;top:0;z-index:9999;display:flex;align-items:center;padding:10px 18px;background:#17212b;border-bottom:1px solid #31413b;box-shadow:0 2px 8px rgba(0,0,0,.16);">
  <a href="/" style="display:inline-block;padding:7px 11px;border-radius:6px;background:#e4f2ef;color:#075e57;font:600 14px/1.2 -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;text-decoration:none;">{label}</a>
</div>
"""
    body_start = content.lower().find("<body")
    if body_start < 0:
        return navigation + content
    body_end = content.find(">", body_start)
    if body_end < 0:
        return navigation + content
    return content[: body_end + 1] + navigation + content[body_end + 1 :]


def _discovery_options(params):
    ai_only = _first(params, "ai_only", "1")
    if ai_only not in {"0", "1"}:
        raise ValueError("Invalid AI filter")
    pool = _first(params, "pool", "unread")
    query = _first(params, "q").strip()
    # Validate before any mutation, including starting a new round.
    DiscoveryDeck._filter(pool, query, ai_only == "1")
    return {"pool": pool, "query": query, "ai_only": ai_only == "1"}


def dashboard_page(query_string: str) -> str:
    config = current_config()
    lang = _language(config)
    t = _texts(lang)
    store = current_store(config)
    params = parse_qs(query_string)
    search = _first(params, "q").strip()
    favorite_only = _first(params, "favorite") == "1"
    status = _first(params, "status")
    min_score = _optional_int(_first(params, "min_score", "0")) or 0
    lt = library_texts(lang)
    source = _first(params, "source")
    sort = _first(params, "sort", "recommended")
    if sort not in LIBRARY_SORTS:
        sort = "recommended"
    page_size = _optional_int(_first(params, "page_size", "20"))
    if page_size not in {20, 50, 100}:
        page_size = 20
    filters = dict(query=search, favorite=favorite_only, status=status, min_score=min_score, source=source)
    total = store.count_for_library(**filters)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(pages, max(1, _optional_int(_first(params, "page", "1")) or 1))
    papers = store.list_for_library(**filters, limit=page_size, offset=(page - 1) * page_size, sort=sort)
    source_options = [("", t["all"])] + [(name, name) for name in store.library_sources()]
    if source and source not in {value for value, _ in source_options}:
        source_options.append((source, source))
    sort_options = [("recommended", lt["recommended"]), ("published", lt["published"]),
                    ("added", lt["added"]), ("score", lt["score_order"]), ("title", lt["title_order"])]
    stats = store.dashboard_stats()
    reports = list_reports(config)
    run = run_status()
    return_query = urlencode(
        {
            "q": search,
            "favorite": "1" if favorite_only else "0",
            "status": status,
            "min_score": str(min_score),
            "source": source, "sort": sort, "page_size": str(page_size), "page": str(page),
        }
    )

    settings_open = _first(params, "settings") == "1"
    show_onboarding = bool(config.get("web", {}).get("show_onboarding", False))

    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Paper Orbit · Reading Library</title>
  <style>{(Path(__file__).parent / 'literature_radar/assets/library.css').read_text(encoding='utf-8')}</style>
</head>
<body>
  <main class="shell">
    <header class="workspace-header">
      <a class="orbit-brand" href="/discover"><span class="orbit-brand-sigil" aria-hidden="true">✧</span><span>PAPER <i>ORBIT</i><small>LITERATURE RADAR</small></span></a>
      <nav class="orbit-nav" aria-label="{'主导航' if lang == 'zh-CN' else 'Main navigation'}">
        <a href="/discover">{'灵感抽卡' if lang == 'zh-CN' else 'Discover'}</a>
        <a href="/discover#warehouse">{'卡牌仓库' if lang == 'zh-CN' else 'Warehouse'}</a>
        <a href="/discover#lab">{'灵感工坊' if lang == 'zh-CN' else 'Idea lab'}</a>
        <a href="/" class="active" aria-current="page">{'文献库' if lang == 'zh-CN' else 'Library'}</a>
      </nav>
      <div class="top-actions">
        <a class="ghost button" href="/manage">数据与任务</a><span class="local-status">LOCAL WORKSPACE</span>
        <button class="ghost" id="theme-toggle" type="button" onclick="toggleTheme()" aria-pressed="false" title="Switch color theme">◐</button>
        <button class="ghost" type="button" onclick="toggleSettings()">{t['settings']}</button>
      </div>
    </header>
    <section class="library-hero">
      <div><p class="eyebrow">YOUR RESEARCH, IN FOCUS.</p>
        <h1>{'让每一次阅读，<br>成为下一次发现。' if lang == 'zh-CN' else 'Every paper.<br>A new perspective.'}</h1>
        <p class="muted">{'收藏值得思考的研究，记录自己的判断，把线索连成新的问题。' if lang == 'zh-CN' else 'Keep meaningful research, capture your thinking, and connect ideas.'}</p>
        <div class="hero-links"><a href="#library">{'探索文献库' if lang == 'zh-CN' else 'Explore your library'} ↓</a><a href="/discover">{'去抽一组灵感' if lang == 'zh-CN' else 'Discover a new hand'} ↗</a></div>
      </div>
      <div class="library-emblem" aria-hidden="true"><div class="emblem-ring"></div><div class="emblem-ring inner"></div><span>✧</span><small>READ · REFLECT · CONNECT</small></div>
    </section>
    <div class="library-utility">
      <span>{'阅读工作台' if lang == 'zh-CN' else 'Reading workspace'}</span>
      <div><form method="post" action="/language"><input type="hidden" name="language" value="{_other_language(lang)}"><button class="ghost" type="submit">{t['switch_language']}</button></form>
      <button class="ghost" type="button" onclick="showOnboarding()">{t['setup_guide']}</button>
      {('<a class="button ghost" href="/reports/' + quote(reports[0]['name']) + '">' + t['open_latest_report'] + '</a>') if reports else ''}</div>
    </div>

    

    <section class="stats">
      <div class="stat"><strong data-stat="total">{stats['total']}</strong><span>{t['total_papers']}</span></div>
      <div class="stat"><strong data-stat="favorites">{stats['favorites']}</strong><span>{t['favorites']}</span></div>
      <div class="stat"><strong data-stat="to_read">{stats['to_read']}</strong><span>{t['to_read']}</span></div>
      <div class="stat"><strong data-stat="reproduce">{stats['reproduce']}</strong><span>{t['reproduce']}</span></div>
      <div class="stat"><strong data-stat="high_score">{stats['high_score']}</strong><span>{t['high_score']}</span></div>
    </section>

    <details class="collection-drawer"><summary><span>✦ &nbsp; {t['run_analysis']} / {t['report_archive']}</span><small>{'展开管理文献来源与搜集任务' if lang == 'zh-CN' else 'Manage collection & reports'}</small></summary>
    <section class="grid">
      <div class="panel">
        <div class="panel-title">
          <div>
            <h2>{t['run_analysis']}</h2>
            <p class="muted">{t['backend']}: {escape(deepseek_status(config))}</p>
          </div>
        </div>
        <form id="run-analysis-form" data-running="{'1' if run['running'] else '0'}" method="post" action="/run" class="form-row" style="margin-top: 12px;">
          <div><label>{t['days_back']}</label><input name="days" value="{config['run']['days_back']}"></div>
          <div><label>{t['max_per_source']}</label><input name="max_per_source" value="{config['run']['max_papers_per_source']}"></div>
          <div><label>{t['min_score']}</label><input name="min_score" value="{config['run']['min_score']}"></div>
          <div><button id="run-analysis-button" type="submit" {'disabled' if run['running'] else ''}>{t['running'] if run['running'] else t['start_analysis']}</button></div>
        </form>
        <p style="margin-top: 10px;" class="muted">{t['status']}: {escape(_localized_run_message(run['message'], lang))}</p>
        <div class="log" id="run-log">{escape(chr(10).join(run['tail']))}</div>
      </div>

      <div class="panel">
        <div class="panel-title">
          <div>
            <h2>{t['report_archive']}</h2>
            <p class="muted">{t['report_archive_hint']}</p>
          </div>
        </div>
        <div class="reports">{_render_reports(reports, lang)}</div>
      </div>
    </section>

    </details>

    <section class="panel settings-panel {' ' if settings_open else 'is-hidden'}" id="settings-panel">
      <div class="panel-title">
        <div>
          <h2>{t['settings']}</h2>
          <p class="muted">{t['settings_hint']}</p>
        </div>
        <button class="ghost" type="button" onclick="toggleSettings()">{t['close']}</button>
      </div>
      {_settings_feedback_html()}
      {_settings_form(config, lang)}
    </section>

    <section class="panel" id="library" style="margin-top: 16px;">
      <h2>{t['paper_library']}</h2>
      <p id="library-refresh-notice" class="notice ok" role="status" hidden>{lt['refresh']} <a href="/?{escape(return_query)}#library">{'刷新' if lang == 'zh-CN' else 'Refresh'}</a></p>
      <p class="muted" id="search-hint" style="margin-bottom:12px;">{lt['search_hint']}</p>
      <form method="get" action="/#library" class="filters">
        <div><label>{t['search']}</label><input name="q" aria-label="{t['search']}" aria-describedby="search-hint" value="{escape(search)}" placeholder="{t['search_placeholder']}"></div>
        <div><label>{t['paper_status']}</label>{_status_select(status, include_blank=True, lang=lang)}</div>
        <div><label>{t['min_score']}</label><input name="min_score" value="{min_score}"></div>
        <div><label>{t['favorite_only']}</label><select name="favorite"><option value="0">{t['no']}</option><option value="1" {'selected' if favorite_only else ''}>{t['yes']}</option></select></div>
        <div><label>{lt['source_filter']}</label>{_select('source', source, source_options)}</div>
        <div><label>{lt['sort']}</label>{_select('sort', sort, sort_options)}</div>
        <div><label>{lt['page_size']}</label>{_select('page_size', str(page_size), [(str(n), str(n)) for n in (20, 50, 100)])}</div>
        <div class="library-actions"><button type="submit">{t['filter']}</button><a href="/#library">{lt['reset']}</a></div>
      </form>
      {render_pagination(total, page, page_size, return_query, lang)}
      <div style="margin-top: 12px;">{_render_papers(papers, return_query, lang)}</div>
      {render_pagination(total, page, page_size, return_query, lang) if papers else ''}
    </section>
  </main>
  <script>
    {library_script(lang)}
    function applyTheme(theme) {{
      document.documentElement.dataset.theme = theme;
      try {{ localStorage.setItem('literature-radar-theme', theme); }} catch (_error) {{}}
      const button = document.getElementById('theme-toggle');
      if (button) {{
        const dark = theme === 'dark';
        button.textContent = dark ? '☀' : '◐';
        button.setAttribute('aria-pressed', String(dark));
      }}
    }}
    function toggleTheme() {{
      applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    }}
    let savedTheme = null;
    try {{ savedTheme = localStorage.getItem('literature-radar-theme'); }} catch (_error) {{}}
    applyTheme(savedTheme || 'dark');
    function toggleSettings() {{
      const panel = document.getElementById('settings-panel');
      if (!panel) return;
      panel.classList.toggle('is-hidden');
      if (!panel.classList.contains('is-hidden')) {{
        panel.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
    }}
    function showOnboarding() {{
      if (window.orbitTour) {{ window.orbitTour.start(); return; }}
      const panel = document.getElementById('onboarding-panel');
      if (!panel) return;
      panel.classList.remove('is-hidden');
      panel.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }}
    async function dismissOnboarding() {{
      const panel = document.getElementById('onboarding-panel');
      if (panel) panel.classList.add('is-hidden');
      try {{
        await fetch('/onboarding/dismiss', {{ method: 'POST' }});
      }} catch (_error) {{}}
    }}
    async function openSettingsFromGuide() {{
      const settings = document.getElementById('settings-panel');
      if (settings) {{
        settings.classList.remove('is-hidden');
        settings.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
      await dismissOnboarding();
    }}
    const runForm = document.getElementById('run-analysis-form');
    let observedActiveRun = runForm?.dataset.running === '1';
    async function refreshRunStatus() {{
      try {{
        const response = await fetch('/api/run-status');
        if (!response.ok) throw new Error('Run status request failed');
        const status = await response.json();
        const log = document.getElementById('run-log');
        if (log) {{
          log.textContent = status.tail.join('\\n');
          log.scrollTop = log.scrollHeight;
        }}
        if (status.running) {{
          observedActiveRun = true;
          setTimeout(refreshRunStatus, 1500);
          return;
        }}
        if (observedActiveRun) {{
          observedActiveRun = false;
          const button = document.getElementById('run-analysis-button');
          if (button) {{ button.disabled = false; button.textContent = {json.dumps(t['start_analysis'])}; }}
          if (hasUnsavedLibraryChanges()) showLibraryRefreshNotice();
          else window.location.reload();
        }}
      }} catch (_error) {{
        setTimeout(refreshRunStatus, 1500);
      }}
    }}
    refreshRunStatus();
    if (new URLSearchParams(window.location.search).get('settings') === '1') {{
      const panel = document.getElementById('settings-panel');
      if (panel) panel.classList.remove('is-hidden');
    }}
  </script>
</body>
</html>"""


def error_page(exc: Exception) -> str:
    backup_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".bak")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bioinfo Literature Workspace - Error</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 860px; margin: 40px auto; padding: 0 18px; }}
    .panel {{ background: white; border: 1px solid #d8dee8; border-radius: 8px; padding: 18px; }}
    code, pre {{ background: #eef2f7; border-radius: 6px; }}
    pre {{ padding: 12px; white-space: pre-wrap; overflow: auto; }}
    .muted {{ color: #667085; }}
  </style>
</head>
<body>
  <main>
    <div class="panel">
      <h1>Workspace failed to render</h1>
      <p class="muted">The server is running, but the page could not load. This is usually caused by an invalid <code>config.toml</code>.</p>
      <h2>Error</h2>
      <pre>{escape(type(exc).__name__ + ': ' + str(exc))}</pre>
      <h2>Recovery</h2>
      <p>If a backup exists, run this in PowerShell:</p>
      <pre>Copy-Item config.toml.bak config.toml -Force</pre>
      <p class="muted">Backup path expected: {escape(str(backup_path))}</p>
    </div>
  </main>
</body>
</html>"""


def _settings_form(config: dict, lang: str) -> str:
    t = _texts(lang)
    zh = lang == 'zh-CN'
    ai = config['analysis']['deepseek']
    sources = config['sources']
    def text(cn, en): return cn if zh else en
    def field(name, label, value='', kind='text', hint=''):
        control = (f'<textarea id="setting-{name}" name="{name}" rows="3">{escape(str(value))}</textarea>' if kind == 'textarea'
                   else f'<input id="setting-{name}" name="{name}" type="{kind}" value="{escape(str(value), quote=True)}"' + (' autocomplete="new-password"' if kind == 'password' else '') + '>')
        return f'<div class="setting-field"><label for="setting-{name}">{escape(label)}</label>{control}' + (f'<small>{escape(hint)}</small>' if hint else '') + '</div>'
    def group(title, hint, body):
        return f'<section class="setting-card"><h3>{title}</h3><p class="setting-hint">{hint}</p>{body}</section>'
    def advanced(title, body):
        return f'<details class="setting-advanced"><summary>{title}</summary><div class="setting-fields">{body}</div></details>'
    mode = 'deepseek' if config['analysis'].get('mode') == 'deepseek' and ai.get('enabled', True) else 'heuristic'
    mode_control = '<div class="setting-field"><label for="setting-analysis-mode">'+text('分析方式','Analysis method')+'</label><select id="setting-analysis-mode" name="analysis_mode">'+''.join(f'<option value="{value}"'+(' selected' if mode==value else '')+f'>{label}</option>' for value,label in [('heuristic',text('规则初筛 · 不调用 AI','Rule screening · no AI calls')),('deepseek',text('AI 解读与评分 · 使用自己的密钥','AI analysis & scoring · your API key'))])+'</select></div>'
    basic = group(text('01 / 研究偏好','01 / Research interests'),text('填写感兴趣的关键词，每行一个。用于文献筛选和推荐；各来源的检索范围可在下方高级选项调整。','One keyword per line for filtering and recommendations. Source queries are available below.'),field('include_keywords',text('感兴趣的关键词','Keywords of interest'),_join_lines(config['profile'].get('include_keywords',[])),'textarea'))
    basic += group(text('02 / 文献搜集','02 / Collection'),text('选择来源和时间范围，其余参数可以先用默认值。','Choose sources and a date range; other defaults are ready to use.'),'<div class="checks">'+''.join(_source_checkbox(config,k) for k in ['pubmed','biorxiv','arxiv','openalex'])+'</div><div class="setting-fields">'+field('run_days_back',t['days_back'],config['run']['days_back'],'number')+field('run_max_per_source',t['max_per_source'],config['run']['max_papers_per_source'],'number')+'</div>')
    basic += group(text('03 / AI（可选）','03 / AI (optional)'),text('不配置也能搜集和管理文献。AI 评级与科研想法需要密钥，调用可能产生费用。','Collect and manage papers without AI. AI ratings and idea generation need a key and may incur costs.'),'<div class="setting-fields">'+mode_control+field('deepseek_api_key',t['deepseek_api_key']+' · '+mask_secret(get_secret(ai.get('api_key_env','DEEPSEEK_API_KEY'))),'','password',text('留空保留现有密钥；选择 AI 后无需再单独开启服务。','Leave blank to keep your key. Selecting AI also enables the service.'))+'</div>')
    search_fields=''.join(field(k+'_query',t[k+'_query'],sources[k].get('query',''),'textarea') for k in ['pubmed','arxiv','openalex'])
    search_fields+=field('core_keywords',t['core_keywords'],_join_lines(config['profile'].get('core_keywords',[])),'textarea')+field('exclude_keywords',t['exclude_keywords'],_join_lines(config['profile'].get('exclude_keywords',[])),'textarea')
    search_fields+=field('weights',t['weights'],_weights_text(config.get('weights',{})),'textarea')+field('run_min_score',t['run_min_score'],config['run']['min_score'],'number')
    model_fields=field('deepseek_model',t['deepseek_model'],ai.get('model','deepseek-v4-flash'))+field('deepseek_base_url',t['base_url'],ai.get('base_url','https://api.deepseek.com'))+field('analysis_language',t['analysis_language'],config['analysis'].get('language','zh-CN'))
    for name,key,label,default in [('deepseek_max_tokens','max_tokens','max_tokens',1800),('deepseek_temperature','temperature','temperature',0.2),('deepseek_min_score','min_heuristic_score','deepseek_min_score',8)]:
        model_fields+=field(name,t[label],ai.get(key,default))
    service_fields=field('pubmed_email',t['pubmed_email'],sources['pubmed'].get('email',''))+field('openalex_mailto',t['openalex_mailto'],sources['openalex'].get('mailto',''))
    service_fields+=field('pubmed_api_key','NCBI API key','','password',t['keep_current_key'])+field('openalex_api_key','OpenAlex API key','','password',t['keep_current_key'])
    service_fields+=field('pubmed_journals',t['watched_journals'],_join_lines(sources['pubmed'].get('journals',[])),'textarea')
    for name,label in [('enable_journal_watch','journal_watch'),('journal_profile_filter','journal_filter')]:
        service_fields+='<div class="setting-field"><label>'+t[label]+'</label>'+_select('pubmed_'+name,str(sources['pubmed'].get(name,True)).lower(),[('true',text('开启','On')),('false',text('关闭','Off'))])+'</div>'
    service_fields+=field('pubmed_journal_max_results',t['journal_max'],sources['pubmed'].get('journal_max_results',20),'number')
    for key,label,default in [('timeout_seconds','openalex_timeout',12),('max_results','openalex_max_results',20),('cooldown_minutes','openalex_cooldown',30)]:
        service_fields+=field('openalex_'+key,t[label],sources['openalex'].get(key,default),'number')
    deletes='<div class="setting-key-actions">'+''.join(f'<label class="check"><input type="checkbox" name="delete_{key}_key" value="1">'+text('删除已保存的 ','Delete saved ')+label+'</label>' for key,label in [('deepseek','AI key'),('pubmed','NCBI key'),('openalex','OpenAlex key')])+'</div>'
    return '<form class="simple-settings" method="post" action="/settings"><input type="hidden" name="simple_settings" value="1"><div class="settings-basics">'+basic+'</div><div class="settings-more"><h3>'+text('高级选项','Advanced options')+'</h3><p class="setting-hint">'+text('通常无需修改。展开后可精确调整，收起的配置仍会保留。','Usually no changes needed. Collapsed settings are preserved when you save.')+'</p>'+advanced(text('检索式与筛选规则','Queries & filtering'),search_fields)+advanced(text('模型与生成参数','Model & generation'),model_fields)+advanced(text('来源账号、期刊与密钥管理','Source accounts, journals & keys'),service_fields+deletes)+'</div><div class="settings-save"><span>'+text('保存后继续使用，不会自动发起搜集或 AI 请求。','Saving does not start collection or AI requests.')+'</span><button type="submit">'+t['save_configuration']+'</button></div></form>'


def save_settings(params: dict[str, list[str]]) -> None:
    config = current_config()
    config["analysis"]["mode"] = _first(params, "analysis_mode", "heuristic")
    config["analysis"]["language"] = _first(params, "analysis_language", "zh-CN")
    deepseek = config["analysis"]["deepseek"]
    deepseek["enabled"] = (config["analysis"]["mode"] == "deepseek") if _first(params, "simple_settings") == "1" else _first(params, "deepseek_enabled", "true") == "true"
    deepseek["model"] = _first(params, "deepseek_model", "deepseek-v4-flash")
    deepseek["base_url"] = validate_ai_url(_first(params, "deepseek_base_url", "https://api.deepseek.com"))
    deepseek["max_tokens"] = _optional_int(_first(params, "deepseek_max_tokens")) or 1800
    deepseek["temperature"] = _optional_float(_first(params, "deepseek_temperature")) or 0.2
    deepseek["min_heuristic_score"] = _optional_int(_first(params, "deepseek_min_score")) or 8

    api_key = _first(params, "deepseek_api_key").strip()
    if _first(params,"delete_deepseek_key")=="1":
        delete_secret(deepseek.get("api_key_env", "DEEPSEEK_API_KEY"))
    elif api_key:
        save_secret(deepseek.get("api_key_env", "DEEPSEEK_API_KEY"), api_key)

    config["run"]["days_back"] = _optional_int(_first(params, "run_days_back")) or config["run"]["days_back"]
    config["run"]["max_papers_per_source"] = _optional_int(_first(params, "run_max_per_source")) or config["run"]["max_papers_per_source"]
    config["run"]["min_score"] = _optional_int(_first(params, "run_min_score")) or config["run"]["min_score"]

    for source in ["pubmed", "biorxiv", "arxiv", "openalex"]:
        config["sources"][source]["enabled"] = _first(params, f"source_{source}") == "1"
    config["sources"]["pubmed"]["email"] = _first(params, "pubmed_email")
    if _first(params,"pubmed_api_key").strip():save_secret("NCBI_API_KEY",_first(params,"pubmed_api_key").strip())
    if _first(params,"delete_pubmed_key")=="1":delete_secret("NCBI_API_KEY")
    config["sources"]["pubmed"]["api_key"] = ""
    config["sources"]["pubmed"]["query"] = _first(params, "pubmed_query")
    config["sources"]["pubmed"]["enable_journal_watch"] = _first(params, "pubmed_enable_journal_watch", "true") == "true"
    config["sources"]["pubmed"]["journal_profile_filter"] = _first(params, "pubmed_journal_profile_filter", "true") == "true"
    config["sources"]["pubmed"]["journal_max_results"] = _optional_int(_first(params, "pubmed_journal_max_results")) or 20
    config["sources"]["pubmed"]["journals"] = _lines(_first(params, "pubmed_journals"))
    config["sources"]["arxiv"]["query"] = _first(params, "arxiv_query")
    if _first(params,"openalex_api_key").strip():save_secret("OPENALEX_API_KEY",_first(params,"openalex_api_key").strip())
    if _first(params,"delete_openalex_key")=="1":delete_secret("OPENALEX_API_KEY")
    config["sources"]["openalex"]["mailto"] = _first(params, "openalex_mailto")
    config["sources"]["openalex"]["query"] = _first(params, "openalex_query")
    config["sources"]["openalex"]["timeout_seconds"] = _optional_int(_first(params, "openalex_timeout_seconds")) or 12
    config["sources"]["openalex"]["max_results"] = _optional_int(_first(params, "openalex_max_results")) or 20
    config["sources"]["openalex"]["cooldown_minutes"] = _optional_int(_first(params, "openalex_cooldown_minutes")) or 30

    config["profile"]["include_keywords"] = _lines(_first(params, "include_keywords"))
    config["profile"]["core_keywords"] = _lines(_first(params, "core_keywords"))
    config["profile"]["exclude_keywords"] = _lines(_first(params, "exclude_keywords"))
    config["weights"] = _parse_weights(_first(params, "weights"))
    write_config(config, CONFIG_PATH)


def save_language(language: str) -> None:
    config = current_config()
    config.setdefault("web", {})["language"] = language if language in {"zh-CN", "en-US"} else "zh-CN"
    write_config(config, CONFIG_PATH)


def set_settings_feedback(message: str = "", error: str = "") -> None:
    global LAST_SETTINGS_ERROR, LAST_SETTINGS_MESSAGE
    LAST_SETTINGS_MESSAGE = message
    LAST_SETTINGS_ERROR = error
    if error:
        RUN_LOG.append(f"[{datetime.now().isoformat(timespec='seconds')}] Settings save failed: {error}")
    elif message:
        RUN_LOG.append(f"[{datetime.now().isoformat(timespec='seconds')}] {message}")


def _settings_feedback_html() -> str:
    if LAST_SETTINGS_ERROR:
        return f'<div class="notice error">Settings save failed: {escape(LAST_SETTINGS_ERROR)}</div>'
    if LAST_SETTINGS_MESSAGE:
        return f'<div class="notice ok">{escape(LAST_SETTINGS_MESSAGE)}</div>'
    return ""


def dismiss_onboarding() -> None:
    config = current_config()
    config.setdefault("web", {})["show_onboarding"] = False
    write_config(config, CONFIG_PATH)


def current_config() -> dict:
    try:
        return load_config(CONFIG_PATH)
    except Exception as exc:
        backup_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".bak")
        if backup_path.exists():
            try:
                config = load_config(backup_path)
                shutil.copyfile(backup_path, CONFIG_PATH)
                set_settings_feedback(message=f"Recovered config.toml from backup after: {type(exc).__name__}: {exc}")
                return config
            except Exception:
                pass
        raise


def current_store(config: dict | None = None) -> PaperStore:
    config = config or current_config()
    store = PaperStore(ROOT / config["project"]["database"])
    store.initialize()
    return store


def list_reports(config: dict) -> list[dict[str, str]]:
    report_dir = ROOT / config["project"]["report_dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in sorted(report_dir.glob("*.html"), key=lambda item: item.stat().st_mtime, reverse=True):
        reports.append(
            {
                "name": path.name,
                "size": f"{path.stat().st_size / 1024:.1f} KB",
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return reports


def start_run(days: int | None = None, max_per_source: int | None = None, min_score: int | None = None) -> None:
    config=copy.deepcopy(current_config())
    for key,value in [('days_back',days),('max_papers_per_source',max_per_source),('min_score',min_score)]:
        if value is not None:config['run'][key]=value
    ensure_collection(TaskStore(current_store(config)),config,ROOT,force=True)


def run_status() -> dict:
    job=TaskStore(current_store()).latest('collection')
    if job is None:return {'running':False,'message':'not started from workspace yet','tail':RUN_LOG[-60:]}
    running=job['status']=='running'
    message='running since '+datetime.fromtimestamp(job['started']).isoformat(timespec='seconds') if running else (
        'completed successfully' if job['status'] in {'succeeded','partial'} else job['error'])
    return {'running':running,'message':message,'tail':(job['log']+RUN_LOG)[-60:],'job':job}


def _render_reports(reports: list[dict[str, str]], lang: str) -> str:
    t = _texts(lang)
    if not reports:
        return f'<p class="muted">{t["no_reports"]}</p>'
    return "\n".join(
        f"""<div class="report-link">
          <a href="/reports/{quote(report['name'])}">{escape(report['name'])}</a>
          <span class="muted">{escape(report['mtime'])} · {escape(report['size'])}</span>
        </div>"""
        for report in reports[:12]
    )


def _onboarding_html(t: dict[str, str], visible: bool) -> str:
    hidden = "" if visible else " is-hidden"
    return f"""
    <section class="panel onboarding{hidden}" id="onboarding-panel">
      <div class="panel-title">
        <div class="onboarding-copy">
          <h2>{t['onboarding_title']}</h2>
          <p class="muted">{t['onboarding_intro']}</p>
        </div>
      </div>
      <div class="guide-grid">
        <div class="guide-step"><span class="guide-number">1</span><div><strong>{t['onboarding_deepseek_title']}</strong><p>{t['onboarding_deepseek_body']}</p></div></div>
        <div class="guide-step"><span class="guide-number">2</span><div><strong>{t['onboarding_pubmed_title']}</strong><p>{t['onboarding_pubmed_body']}</p></div></div>
        <div class="guide-step"><span class="guide-number">3</span><div><strong>{t['onboarding_search_title']}</strong><p>{t['onboarding_search_body']}</p></div></div>
      </div>
      <div class="guide-actions">
        <button type="button" onclick="openSettingsFromGuide()">{t['onboarding_open_settings']}</button>
        <button class="ghost" type="button" onclick="dismissOnboarding()">{t['onboarding_dismiss']}</button>
      </div>
    </section>
    """


def _render_papers(papers, return_query: str, lang: str) -> str:
    t = _texts(lang)
    if not papers:
        return f'<p class="muted">{t["no_matching_papers"]}</p>'
    return "\n".join(_render_paper(row, return_query, lang) for row in papers)


def _render_paper(row, return_query: str, lang: str) -> str:
    t = _texts(lang)
    analysis = json.loads(row["analysis_json"] or "{}")
    tags = json.loads(row["tags_json"] or "[]")
    authors = json.loads(row["authors_json"] or "[]")
    card_class = "paper favorite" if row["favorite"] else "paper"
    summary = analysis.get("summary") or ""
    provider = analysis.get("provider") or "heuristic"
    tier = rarity(row['score'], provider)
    tier_label = tier if tier != 'UNRATED' else ('待评级' if lang == 'zh-CN' else 'Unrated')
    source_warning = ('来源标记撤稿/撤稿通知' if lang=='zh-CN' else 'Source flags retraction/notice') if analysis.get('retraction_status') in {'retracted','retraction_notice'} else ('预印本 · 请核对正式版本' if lang=='zh-CN' else 'Preprint: check published version') if row['source'] in {'arxiv','biorxiv','medrxiv'} else ('请核对版本与撤稿状态' if lang=='zh-CN' else 'Verify version and retraction status')
    tag_html = "".join(f'<span class="tag">{escape(str(tag))}</span>' for tag in tags[:10])
    authors_text = ", ".join(authors[:6]) + (", et al." if len(authors) > 6 else "")
    favorite_select = _select("favorite", "1" if row["favorite"] else "0", [("0", t["not_favorite"]), ("1", t["favorite"])])
    return f"""
    <article class="{card_class}" id="paper-{row['id']}" data-tier="{tier}">
      <div class="paper-head">
        <div>
          <div class="title">{escape(row['title'])}</div>
          <p class="muted">{escape(row['source'])} · {escape(row['published'] or 'unknown')} · {escape(row['journal'] or 'N/A')}</p>
          <p class="muted">{escape(authors_text or 'N/A')}</p>
        </div>
        <div class="score"><strong>{tier_label}</strong><span>{('AI ' if tier != 'UNRATED' else t['score'] + ' ') + str(row['score'])}{' / 30' if tier != 'UNRATED' else ''}</span></div>
      </div>
      <div class="tags">{tag_html or '<span class="tag">none</span>'}</div>
      <p>{escape(summary or t['no_summary'])}</p>
      <p style="margin-top: 8px;"><span class="pill">{t['analysis']}: {escape(provider)}</span> <a href="{escape(safe_source_url(row['url'] or ''))}" target="_blank" rel="noreferrer">{t['source']}</a></p>
      {('<p class="muted">DOI: ' + escape(row['doi']) + '</p>') if row['doi'] else ''}
      <p class="muted">{source_warning} · {'评级基于标题与摘要，仅供阅读排序' if lang == 'zh-CN' else 'Title/abstract-based reading priority only'}</p>
      {render_details(row, analysis, lang)}
      <form method="post" action="/paper/update" class="paper-tools">
        <input type="hidden" name="paper_id" value="{row['id']}">
        <input type="hidden" name="return_query" value="{escape(return_query)}">
        <div><label>{t['favorite_label']}</label>{favorite_select}</div>
        <div><label>{t['paper_status']}</label>{_status_select(row['read_status'], lang=lang)}</div>
        <div><label>{t['personal_note']}</label><textarea name="user_note" placeholder="{t['note_placeholder']}">{escape(row['user_note'] or '')}</textarea></div>
        <div><label>&nbsp;</label><button type="submit">{t['save']}</button><span class="save-feedback" role="status" aria-live="polite"></span><small class="muted">Ctrl + Enter</small></div>
      </form>
    </article>
    """


def _status_select(current: str, include_blank: bool = False, lang: str = "zh-CN") -> str:
    t = _texts(lang)
    statuses = [
        ("new", t["status_new"]),
        ("to_read", t["status_to_read"]),
        ("reading", t["status_reading"]),
        ("read", t["status_read"]),
        ("reproduce", t["status_reproduce"]),
        ("ignore", t["status_ignore"]),
    ]
    options = [("", t["all"])] if include_blank else []
    options.extend(statuses)
    return _select("status" if include_blank else "read_status", current, options)


def _select(name: str, current: str, options: list[tuple[str, str]]) -> str:
    body = []
    for value, label in options:
        selected = "selected" if str(current) == str(value) else ""
        body.append(f'<option value="{escape(value)}" {selected}>{escape(label)}</option>')
    return f'<select name="{escape(name)}">{"".join(body)}</select>'


def _source_checkbox(config: dict, source: str) -> str:
    checked = "checked" if config["sources"][source].get("enabled") else ""
    return f'<label class="check"><input type="checkbox" name="source_{source}" value="1" {checked}> {source}</label>'


def _language(config: dict) -> str:
    return config.get("web", {}).get("language", "zh-CN")


def _other_language(lang: str) -> str:
    return "en-US" if lang == "zh-CN" else "zh-CN"


def _localized_run_message(message: str, lang: str) -> str:
    if lang != "zh-CN":
        return message
    if message == "not started from workspace yet":
        return "尚未从工作台启动分析"
    if message.startswith("running since "):
        return "运行中，开始于 " + message.removeprefix("running since ")
    if message == "completed successfully":
        return "\u5206\u6790\u5df2\u5b8c\u6210"
    if message.startswith("failed with exit code "):
        return "\u5206\u6790\u5931\u8d25\uff0c\u9000\u51fa\u7801 " + message.removeprefix("failed with exit code ")
    return message


def _texts(lang: str) -> dict[str, str]:
    zh = {
        "setup_guide": "\u8bbe\u7f6e\u8bf4\u660e",
        "onboarding_title": "\u9996\u6b21\u4f7f\u7528\u8bbe\u7f6e",
        "onboarding_intro": "\u9ed8\u8ba4\u914d\u7f6e\u53ef\u4ee5\u76f4\u63a5\u68c0\u7d22\u3002\u5728\u9996\u6b21\u5206\u6790\u524d\uff0c\u6309\u4e0b\u65b9\u63d0\u793a\u8865\u5145\u60a8\u81ea\u5df1\u7684\u8bbe\u7f6e\u3002",
        "onboarding_deepseek_title": "\u53ef\u9009\uff1aDeepSeek \u5206\u6790",
        "onboarding_deepseek_body": "\u9700\u8981 AI \u89e3\u8bfb\u65f6\uff0c\u5c06\u5206\u6790\u6a21\u5f0f\u6539\u4e3a deepseek\uff0c\u542f\u7528 DeepSeek\uff0c\u518d\u586b\u5165 API key\u3002",
        "onboarding_pubmed_title": "\u5efa\u8bae\uff1a\u8054\u7cfb\u90ae\u7bb1",
        "onboarding_pubmed_body": "\u5728 PubMed email \u548c OpenAlex mailto \u4e2d\u586b\u5199\u90ae\u7bb1\uff0c\u8bbf\u95ee\u4f1a\u66f4\u7a33\u5b9a\u3002PubMed API key \u4e3a\u53ef\u9009\u9879\u3002",
        "onboarding_search_title": "\u81ea\u5b9a\u4e49\u68c0\u7d22\u8303\u56f4",
        "onboarding_search_body": "\u4fee\u6539 PubMed\u3001arXiv\u3001OpenAlex \u68c0\u7d22\u5f0f\u548c\u5305\u542b\u5173\u952e\u8bcd\uff0c\u7136\u540e\u4fdd\u5b58\u914d\u7f6e\u5e76\u5f00\u59cb\u5206\u6790\u3002",
        "onboarding_open_settings": "\u524d\u5f80\u8bbe\u7f6e",
        "onboarding_dismiss": "\u7a0d\u540e\u8bbe\u7f6e",
        "subtitle": "运行每日分析、查看归档、收藏和整理文献。",
        "switch_language": "English",
        "settings": "设置",
        "open_latest_report": "打开最新报告",
        "total_papers": "入库文献",
        "favorites": "收藏",
        "to_read": "待读",
        "reproduce": "可复现",
        "high_score": "高分文献",
        "run_analysis": "启动分析",
        "backend": "后端",
        "days_back": "回溯天数",
        "max_per_source": "每源上限",
        "min_score": "最低分",
        "run_min_score": "运行最低分",
        "running": "运行中",
        "start_analysis": "开始分析",
        "status": "状态",
        "report_archive": "报告归档",
        "report_archive_hint": "最近生成的 HTML 报告。",
        "settings_hint": "API 凭据、数据源、关键词和评分规则。",
        "close": "关闭",
        "paper_library": "文献库",
        "search": "搜索",
        "search_placeholder": "标题、摘要、标签、AI 总结",
        "paper_status": "状态",
        "favorite_only": "只看收藏",
        "yes": "是",
        "no": "否",
        "filter": "筛选",
        "analysis_mode": "分析模式",
        "analysis_language": "分析语言",
        "deepseek_enabled": "启用 DeepSeek",
        "deepseek_api_key": "DeepSeek API key",
        "keep_current_key": "留空则保留当前 key",
        "deepseek_model": "DeepSeek 模型",
        "base_url": "Base URL",
        "max_tokens": "最大 tokens",
        "temperature": "Temperature",
        "deepseek_min_score": "DeepSeek 最低初筛分",
        "enabled_sources": "启用数据源",
        "pubmed_email": "PubMed 邮箱",
        "openalex_mailto": "OpenAlex 邮箱（建议填写，减少 429）",
        "pubmed_query": "PubMed 检索式",
        "journal_watch": "重点期刊监控",
        "journal_filter": "按画像关键词过滤期刊",
        "journal_max": "重点期刊结果上限",
        "watched_journals": "重点监控期刊，一行一个",
        "arxiv_query": "arXiv 检索式",
        "openalex_query": "OpenAlex 检索式",
        "openalex_timeout": "OpenAlex 超时秒数",
        "openalex_max_results": "OpenAlex 单次上限",
        "openalex_cooldown": "OpenAlex 限流冷却分钟",
        "include_keywords": "包含关键词，一行一个",
        "core_keywords": "核心关键词，一行一个",
        "exclude_keywords": "排除关键词，一行一个",
        "weights": "权重，一行一个：keyword=score",
        "save_configuration": "保存配置",
        "no_reports": "还没有报告。先启动一次分析。",
        "no_matching_papers": "没有匹配文献。",
        "not_favorite": "未收藏",
        "favorite": "收藏",
        "score": "分数",
        "no_summary": "暂无总结。",
        "analysis": "分析",
        "source": "原文",
        "favorite_label": "收藏",
        "personal_note": "个人笔记",
        "note_placeholder": "为什么收藏、和课题的关系、复现想法",
        "save": "保存",
        "all": "全部",
        "status_new": "新入库",
        "status_to_read": "待读",
        "status_reading": "精读中",
        "status_read": "已读",
        "status_reproduce": "可复现",
        "status_ignore": "忽略",
    }
    en = {
        "setup_guide": "Setup guide",
        "onboarding_title": "First-time setup",
        "onboarding_intro": "The default profile can search immediately. Before your first analysis, review the settings below and add your own details.",
        "onboarding_deepseek_title": "Optional: DeepSeek analysis",
        "onboarding_deepseek_body": "For AI analysis, change Analysis mode to deepseek, enable DeepSeek, and paste an API key.",
        "onboarding_pubmed_title": "Recommended: contact emails",
        "onboarding_pubmed_body": "Add your email to PubMed email and OpenAlex mailto for more reliable access. A PubMed API key is optional.",
        "onboarding_search_title": "Customize search scope",
        "onboarding_search_body": "Adjust the PubMed, arXiv, and OpenAlex queries plus include keywords, then save and start analysis.",
        "onboarding_open_settings": "Open settings",
        "onboarding_dismiss": "Set up later",
        "subtitle": "Run daily analysis, browse archives, and curate papers without leaving the local workspace.",
        "switch_language": "中文",
        "settings": "Settings",
        "open_latest_report": "Open latest report",
        "total_papers": "Total papers",
        "favorites": "Favorites",
        "to_read": "To read",
        "reproduce": "Reproduce",
        "high_score": "High score",
        "run_analysis": "Run Analysis",
        "backend": "Backend",
        "days_back": "Days back",
        "max_per_source": "Max per source",
        "min_score": "Min score",
        "run_min_score": "Run min score",
        "running": "Running",
        "start_analysis": "Start analysis",
        "status": "Status",
        "report_archive": "Report Archive",
        "report_archive_hint": "Recent generated HTML reports.",
        "settings_hint": "API credentials, sources, keywords, and scoring rules.",
        "close": "Close",
        "paper_library": "Paper Library",
        "search": "Search",
        "search_placeholder": "title, abstract, tags, AI summary",
        "paper_status": "Status",
        "favorite_only": "Favorite only",
        "yes": "Yes",
        "no": "No",
        "filter": "Filter",
        "analysis_mode": "Analysis mode",
        "analysis_language": "Language",
        "deepseek_enabled": "DeepSeek enabled",
        "deepseek_api_key": "DeepSeek API key",
        "keep_current_key": "leave blank to keep current key",
        "deepseek_model": "DeepSeek model",
        "base_url": "Base URL",
        "max_tokens": "Max tokens",
        "temperature": "Temperature",
        "deepseek_min_score": "DeepSeek min heuristic score",
        "enabled_sources": "Enabled sources",
        "pubmed_email": "PubMed email",
        "openalex_mailto": "OpenAlex mailto (recommended to reduce 429)",
        "pubmed_query": "PubMed query",
        "journal_watch": "Journal watch",
        "journal_filter": "Filter journals by profile keywords",
        "journal_max": "Journal-watch max results",
        "watched_journals": "Watched journals, one per line",
        "arxiv_query": "arXiv query",
        "openalex_query": "OpenAlex query",
        "openalex_timeout": "OpenAlex timeout seconds",
        "openalex_max_results": "OpenAlex max results",
        "openalex_cooldown": "OpenAlex cooldown minutes",
        "include_keywords": "Include keywords, one per line",
        "core_keywords": "Core keywords, one per line",
        "exclude_keywords": "Exclude keywords, one per line",
        "weights": "Weights, one per line: keyword=score",
        "save_configuration": "Save configuration",
        "no_reports": "No reports yet. Start an analysis first.",
        "no_matching_papers": "No matching papers.",
        "not_favorite": "not favorite",
        "favorite": "favorite",
        "score": "score",
        "no_summary": "No summary available.",
        "analysis": "Analysis",
        "source": "source",
        "favorite_label": "Favorite",
        "personal_note": "Personal note",
        "note_placeholder": "why save it, relation to topic, reproduction idea",
        "save": "Save",
        "all": "all",
        "status_new": "new",
        "status_to_read": "to read",
        "status_reading": "reading",
        "status_read": "read",
        "status_reproduce": "reproduce",
        "status_ignore": "ignore",
    }
    return zh if lang == "zh-CN" else en


def _join_lines(items: list[str]) -> str:
    return "\n".join(str(item) for item in items)


def _weights_text(weights: dict[str, int]) -> str:
    return "\n".join(f"{key}={value}" for key, value in weights.items())


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _parse_weights(value: str) -> dict[str, int]:
    weights: dict[str, int] = {}
    for line in value.splitlines():
        if not line.strip() or "=" not in line:
            continue
        key, raw_score = line.split("=", 1)
        score = _optional_int(raw_score.strip())
        if key.strip() and score is not None:
            weights[key.strip()] = score
    return weights


def _first(params: dict[str, list[str]], key: str, default: str = "") -> str:
    return params.get(key, [default])[0]


def _optional_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local literature workspace.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_loopback(args.host)
    from literature_radar.paths import acquire_workspace_lock, prepare_workspace, startup_backup, migrate_config_credentials
    acquire_workspace_lock();prepare_workspace();migrate_config_credentials();startup_backup()
    server = ThreadingHTTPServer((args.host, args.port), LiteratureHandler)
    print(f"Bioinfo Literature Workspace: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
