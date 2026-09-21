import copy
import json
import os
from pathlib import Path
from http.client import HTTPConnection
from unittest.mock import patch
import unittest
import uuid
import sqlite3

import test_library as fixtures
from literature_radar.backup import snapshot,restore,validate_backup,database_connection
from literature_radar.security import SESSION_TOKEN,MAX_BODY,require_loopback
from literature_radar.discovery import DiscoveryDeck
from literature_radar.models import Paper,PaperAnalysis
from literature_radar.workflows import TaskStore
from literature_radar.usage import ai_request,BudgetExceeded,usage_summary
from literature_radar import secrets

class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LibraryTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.store=self.fixture.store

    def request(self,method,path,body='',headers=None):
        port=self.fixture.start_server();c=HTTPConnection('127.0.0.1',port,timeout=3);self.addCleanup(c.close)
        c.request(method,path,body,headers or {});response=c.getresponse();return response.status,response.read(),dict(response.getheaders())

    def test_loopback_and_cross_site_requests_are_rejected(self):
        for host in ['0.0.0.0','192.168.0.1','example.com']:
            with self.assertRaises(ValueError):require_loopback(host)
        for headers in [{'Origin':'https://evil.example','X-Orbit-Token':SESSION_TOKEN},
                        {'Host':'evil.example','X-Orbit-Token':SESSION_TOKEN},
                        {'Sec-Fetch-Site':'cross-site','X-Orbit-Token':SESSION_TOKEN},{}]:
            status,_,_=self.request('POST','/language','language=en-US',headers)
            self.assertEqual(status,403)

    def test_cookie_alone_cannot_mutate_and_body_limit_is_enforced(self):
        status,_,_=self.request('POST','/language','language=en-US',{'Cookie':'orbit_session='+SESSION_TOKEN})
        self.assertEqual(status,403)
        status,_,_=self.request('POST','/language','',{'X-Orbit-Token':SESSION_TOKEN,'Content-Length':str(MAX_BODY+1)})
        self.assertEqual(status,413)
        status,_,_=self.request('GET','/api/inventory')
        self.assertEqual(status,403)

    def test_browser_bootstrap_has_csrf_and_security_headers(self):
        status,body,headers=self.request('GET','/')
        self.assertEqual(status,200);self.assertIn(b'name="_csrf"',body)
        self.assertIn('SameSite=Strict',headers['Set-Cookie']);self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertEqual(headers['X-Frame-Options'],'DENY')

    def test_tutorial_progress_is_validated_and_persisted(self):
        from literature_radar.config import load_config
        headers={'X-Orbit-Token':SESSION_TOKEN}
        for body in ['step=-1&active=1','step=8&active=1','step=2&active=yes']:
            self.assertEqual(self.request('POST','/onboarding/progress',body,headers)[0],400)
        self.assertEqual(self.request('POST','/onboarding/progress','step=4&active=1',headers)[0],200)
        self.assertEqual(load_config(self.root/'config.toml')['web']['tutorial_step'],4)
        for path in ['/', '/discover', '/manage']:
            status,body,_=self.request('GET',path)
            self.assertEqual(status,200)
            self.assertIn(b'window.orbitTourState=',body)
        self.assertEqual(self.request('POST','/onboarding/progress','step=7&active=0',headers)[0],200)
        self.assertFalse(load_config(self.root/'config.toml')['web']['show_onboarding'])

    def test_explicit_workspace_does_not_import_legacy_private_data(self):
        from literature_radar import paths
        legacy=self.root/'legacy';legacy.mkdir();(legacy/'installer').mkdir()
        import shutil
        template=Path(__file__).resolve().parents[1]/'installer/config.toml'
        shutil.copyfile(template,legacy/'installer/config.toml')
        (legacy/'config.toml').write_text('private sentinel',encoding='utf-8')
        target=self.root/'clean'
        with patch.dict(os.environ,{'LITERATURE_RADAR_ROOT':str(target)}), patch.object(paths,'resource_root',return_value=legacy):
            paths.prepare_workspace()
        self.assertEqual((target/'config.toml').read_bytes(),template.read_bytes())
        self.assertFalse((target/'data/papers.sqlite').exists())
        self.assertEqual((legacy/'config.toml').read_text(encoding='utf-8'),'private sentinel')

    def test_get_forms_do_not_leak_csrf_token(self):
        from literature_radar.security import secure_html
        html = secure_html('<form method="get"><input name="q"></form><form method="post"></form>')
        self.assertNotIn('_csrf', html.split('</form>')[0])
        self.assertIn('_csrf', html.split('</form>')[1])

    def test_retraction_warning_survives_cross_source_refresh(self):
        paper = Paper(source='openalex',external_id='W1',title='Atlas',abstract='',url='',doi='10.1234/ATLAS_01',raw={'is_retracted':True})
        self.store.upsert_paper(paper)
        paper.source='pubmed';paper.external_id='123';paper.raw={}
        self.store.upsert_paper(paper)
        row=self.store.list_for_library()[0]
        self.assertEqual(json.loads(row['analysis_json'])['retraction_status'],'retracted')

    def test_backup_restore_preserves_warehouse_notes_and_ideas(self):
        self.store.update_user_fields(self.fixture.paper_id,user_note='original private note',favorite=True)
        deck=DiscoveryDeck(self.store);deck.draw(1,str(uuid.uuid4()),ai_only=False)
        TaskStore(self.store)
        path=snapshot(self.store.db_path,self.root/'backups')
        self.store.update_user_fields(self.fixture.paper_id,user_note='newer note')
        before=restore(self.store.db_path,self.root/'backups',path.name)
        self.assertEqual(self.store.list_for_library()[0]['user_note'],'original private note')
        self.assertEqual(deck.inventory()['total'],1)
        with database_connection(self.root/'backups'/before) as conn:
            self.assertEqual(conn.execute('SELECT user_note FROM papers').fetchone()[0],'newer note')

    def test_bad_backup_is_rejected_without_touching_data(self):
        directory=self.root/'backups';directory.mkdir();bad=directory/'bad.sqlite';bad.write_text('not sqlite')
        with self.assertRaises((ValueError,sqlite3.DatabaseError)):restore(self.store.db_path,directory,bad.name)
        with self.assertRaises(ValueError):restore(self.store.db_path,directory,'../bad.sqlite')
        self.assertEqual(self.store.dashboard_stats()['total'],1)

    def test_cross_source_doi_dedup_preserves_user_work(self):
        self.store.update_user_fields(self.fixture.paper_id,user_note='keep',favorite=True)
        self.store.upsert_paper(Paper(source='openalex',external_id='W1',title='Spatial atlas',abstract='Evidence',url='https://example.org',doi='https://doi.org/10.1234/ATLAS_01'))
        self.assertEqual(self.store.dashboard_stats()['total'],1)
        row=self.store.list_for_library()[0];self.assertEqual(row['user_note'],'keep');self.assertTrue(row['favorite'])
        with self.store._connect() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM paper_sources').fetchone()[0],2)

    def test_usage_limit_reserves_failed_calls_and_does_not_retry(self):
        config={**self.fixture.config,'_workspace_root':str(self.root),'budget':{'daily_call_limit':1,'daily_token_limit':10000}}
        with patch('literature_radar.usage.request',side_effect=TimeoutError('private body')) as transport:
            with self.assertRaises(TimeoutError):ai_request(config,'ideas','https://api.deepseek.com/chat/completions',json={'model':'test','max_tokens':10})
            with self.assertRaises(BudgetExceeded):ai_request(config,'ideas','https://api.deepseek.com/chat/completions',json={'max_tokens':10})
            self.assertEqual(transport.call_count,1)
        self.assertEqual(usage_summary(config)[0]['calls'],1)

    @unittest.skipUnless(os.name=='nt','Windows credential integration')
    def test_windows_credentials_rotate_delete_and_migrate(self):
        path=self.root/'legacy.json';name='test-'+uuid.uuid4().hex
        with patch.object(secrets,'SECRETS_PATH',path):
            self.addCleanup(lambda:None)
            try:
                path.write_text(json.dumps({name:'dummy-v1'}));secrets.migrate_legacy()
                self.assertEqual(secrets.get_secret(name),'dummy-v1');self.assertEqual(json.loads(path.read_text()),{})
                secrets.save_secret(name,'dummy-v2');self.assertEqual(secrets.get_secret(name),'dummy-v2')
                secrets.delete_secret(name);self.assertEqual(secrets.get_secret(name),'')
            finally:secrets.delete_secret(name)

    def test_report_links_block_active_schemes(self):
        from datetime import date
        from literature_radar.report import write_html_report,write_markdown_report
        paper=Paper(source='test',external_id='x',title='<script>bad</script> [x](javascript:bad)',abstract='',url='javascript:alert(1)')
        target=self.root/'report.html';write_html_report([paper],target,self.fixture.config,date.today(),date.today())
        self.assertNotIn('href="javascript:',target.read_text(encoding='utf-8'))
        target=self.root/'report.md';write_markdown_report([paper],target,self.fixture.config,date.today(),date.today())
        self.assertNotIn('<script>',target.read_text(encoding='utf-8'));self.assertNotIn('[x](javascript:',target.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
