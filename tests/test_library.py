from __future__ import annotations

import copy
import json
import re
import tempfile
import threading
import unittest
from datetime import date
from http.client import HTTPConnection as BaseHTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import web_app
from literature_radar.config import load_config
from literature_radar.library_ui import render_details, safe_source_url
from literature_radar.models import Paper, PaperAnalysis
from literature_radar.storage import PaperStore


class HTTPConnection(BaseHTTPConnection):
    def request(self, method, url, body=None, headers=None, **kwargs):
        from literature_radar.security import SESSION_TOKEN
        headers={'X-Orbit-Token':SESSION_TOKEN,**(headers or {})}
        return super().request(method,url,body,headers,**kwargs)


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = copy.deepcopy(load_config(Path(__file__).resolve().parents[1] / 'installer/config.toml'))
        self.config['project']['database'] = 'papers.sqlite'
        self.config['project']['report_dir'] = 'reports'
        self.config.setdefault('web', {})['language'] = 'zh-CN'
        self.config['web']['show_onboarding'] = False
        for target, value in [('ROOT', self.root), ('CONFIG_PATH', self.root / 'config.toml'), ('current_config', lambda: self.config),
                              ('deepseek_status', lambda _: 'test'), ('get_secret', lambda _: '')]:
            mock = patch.object(web_app, target, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.store = web_app.current_store()
        self.paper = Paper(source='pubmed', external_id='1', title='Spatial atlas',
                           abstract='Original <script>alert(1)</script> abstract',
                           url='https://example.org/paper', doi='10.1234/atlas_01',
                           authors=['Ada Researcher'], journal='Example journal',
                           published=date(2026, 1, 1),
                           analysis=PaperAnalysis(score=20, detailed_summary='Detailed evidence',
                                                  method_flow=['Prepare data', 'Train model'],
                                                  follow_up_prompts=['Validate independently?']))
        self.store.upsert_paper(self.paper)
        self.paper_id = self.store.list_for_library()[0]['id']

    def test_search_authors_doi_notes_and_multiple_fields(self):
        self.store.update_user_fields(self.paper_id, user_note='肿瘤复现计划')
        for query in ['Ada', '10.1234/atlas_01', '肿瘤复现', 'Ada Spatial 肿瘤', 'Detailed evidence']:
            with self.subTest(query=query):
                self.assertEqual(self.store.count_for_library(query=query), 1)
                self.assertEqual(len(self.store.list_for_library(query=query)), 1)
        self.assertEqual(self.store.count_for_library(query='Ada missingword'), 0)

    def test_wildcards_and_sql_are_literal(self):
        for query in ['%', "' OR 1=1 --", '!']:
            self.assertEqual(self.store.count_for_library(query=query), 0)
        self.store.update_user_fields(self.paper_id, user_note='100% gene_x!')
        for query in ['100%', 'gene_x!', '_']:
            self.assertEqual(self.store.count_for_library(query=query), 1)

    def test_all_results_reachable_with_stable_pagination(self):
        for i in range(2, 137):
            self.store.upsert_paper(Paper(source='pubmed', external_id=str(i), title=f'Paper {i:03}',
                                         abstract='', url='', analysis=PaperAnalysis(score=20)))
        ids = []
        for offset in range(0, 136, 20):
            ids.extend(row['id'] for row in self.store.list_for_library(limit=20, offset=offset))
        self.assertEqual(len(ids), 136)
        self.assertEqual(len(set(ids)), 136)
        self.assertEqual(self.store.count_for_library(), 136)
        self.store.update_user_fields(ids[10], user_note='updated')
        self.assertEqual(ids[:20], [r['id'] for r in self.store.list_for_library(limit=20)])

    def test_combined_filters_and_sorts(self):
        self.store.upsert_paper(Paper(source='arxiv', external_id='2', title='Alpha', abstract='', url='',
                                     published=date(2026, 2, 1), analysis=PaperAnalysis(score=30)))
        self.store.update_user_fields(self.paper_id, favorite=True, read_status='reading')
        filters = dict(query='Ada', favorite=True, status='reading', min_score=18, source='pubmed')
        self.assertEqual(self.store.count_for_library(**filters), 1)
        self.assertEqual(self.store.list_for_library(**filters)[0]['id'], self.paper_id)
        self.assertEqual(self.store.count_for_library(**{**filters, 'min_score': 25}), 0)
        self.assertEqual(self.store.library_sources(), ['arxiv', 'pubmed'])
        self.assertEqual(self.store.list_for_library()[0]['title'], 'Spatial atlas')
        for sort in ['published', 'score', 'title', 'added']:
            self.assertEqual(self.store.list_for_library(sort=sort)[0]['title'], 'Alpha')
        self.assertEqual(len(self.store.list_for_library(sort='score; DROP TABLE papers')), 2)

    def test_reanalysis_preserves_reading_work(self):
        self.store.update_user_fields(self.paper_id, favorite=True, read_status='read', user_note='My findings')
        self.paper.analysis.score = 35
        self.store.upsert_paper(self.paper)
        row = self.store.list_for_library()[0]
        self.assertEqual((row['favorite'], row['read_status'], row['user_note'], row['score']),
                         (1, 'read', 'My findings', 35))

    def test_invalid_update_does_not_partially_save(self):
        with self.assertRaises(ValueError):
            self.store.update_user_fields(self.paper_id, favorite=True, read_status='unknown')
        self.assertEqual(self.store.list_for_library()[0]['favorite'], 0)
        with self.assertRaises(LookupError):
            self.store.update_user_fields(999, user_note='missing')

    def test_page_bounds_empty_state_and_languages(self):
        for query in ['page=-2', 'page=999&page_size=7', 'page=oops&sort=bad', 'q=notfound&page=500']:
            html = web_app.dashboard_page(query)
            self.assertIn('第 1/1 页', html)
            self.assertIn('id="library"', html)
        self.assertIn('显示 0–0', web_app.dashboard_page('q=notfound'))
        self.assertIn('<html lang="zh-CN">', web_app.dashboard_page(''))
        self.config['web']['language'] = 'en'
        self.assertIn('Showing 1–1', web_app.dashboard_page(''))

    def test_reading_details_escape_content_and_include_all_evidence(self):
        row = self.store.list_for_library()[0]
        html = render_details(row, json.loads(row['analysis_json']), 'en')
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        for value in ['Detailed evidence', 'Prepare data', 'Train model', 'Validate independently?']:
            self.assertIn(value, html)
        self.assertIn('<ol>', html)
        self.assertEqual(safe_source_url('javascript:alert(1)'), '#')
        self.assertEqual(safe_source_url('https://example.org'), 'https://example.org')
        self.assertEqual(safe_source_url('https://['), '#')

    def start_server(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), web_app.LiteratureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(cleanup)
        return server.server_port

    def post(self, port, fields, accept='application/json'):
        connection = HTTPConnection('127.0.0.1', port, timeout=5)
        self.addCleanup(connection.close)
        connection.request('POST', '/paper/update', urlencode(fields),
                           {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': accept})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_http_save_clear_note_and_legacy_redirect(self):
        port = self.start_server()
        fields = dict(paper_id=self.paper_id, favorite='1', read_status='reading', user_note='中文笔记\nSecond line',
                      return_query='q=atlas&page=2')
        status, _, body = self.post(port, fields)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['stats']['favorites'], 1)
        self.assertEqual(self.store.list_for_library()[0]['user_note'], fields['user_note'])
        status, _, _ = self.post(port, {**fields, 'user_note': ''})
        self.assertEqual(status, 200)
        self.assertEqual(self.store.list_for_library()[0]['user_note'], '')
        status, headers, _ = self.post(port, fields, 'text/html')
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/?q=atlas&page=2#library')

    def test_http_invalid_requests_return_errors_without_changes(self):
        port = self.start_server()
        fields = dict(paper_id=self.paper_id, favorite='1', read_status='reading', user_note='note')
        for delta, expected in [({'paper_id': 'abc'}, 400), ({'paper_id': '-1'}, 400),
                                ({'paper_id': '99999'}, 404), ({'read_status': 'bad'}, 400),
                                ({'favorite': 'bad'}, 400)]:
            status, _, body = self.post(port, {**fields, **delta})
            self.assertEqual(status, expected)
            self.assertFalse(json.loads(body)['ok'])
        self.assertEqual(self.post(port, {'paper_id': self.paper_id})[0], 400)
        row = self.store.list_for_library()[0]
        self.assertEqual((row['favorite'], row['read_status'], row['user_note']), (0, 'new', ''))

    def test_storage_failure_is_reported(self):
        port = self.start_server()
        with patch.object(PaperStore, 'update_user_fields', side_effect=RuntimeError('database unavailable')):
            status, _, body = self.post(port, dict(paper_id=self.paper_id, favorite='0', read_status='new', user_note='note'))
        self.assertEqual(status, 500)
        self.assertFalse(json.loads(body)['ok'])

    def test_navigation_preserves_filters_and_reaches_last_page(self):
        for i in range(2, 23):
            self.store.upsert_paper(Paper(source='pubmed', external_id=str(i), title=f'Spatial {i}', abstract='', url=''))
        html = web_app.dashboard_page('q=Spatial&source=pubmed&sort=title&page=2')
        self.assertEqual(len(re.findall(r'<article class="paper', html)), 2)
        self.assertIn('显示 21–22', html)
        self.assertIn('source=pubmed&amp;sort=title&amp;page_size=20&amp;page=1#library', html)


if __name__ == '__main__':
    unittest.main()