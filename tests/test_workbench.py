import copy
import json
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from test_library import HTTPConnection
from urllib.parse import urlencode

import test_library as fixtures
from literature_radar.collector import collect_library
from literature_radar.discovery import DiscoveryDeck
from literature_radar.ideation import generate_ideas, source_snapshots, validate_result, decode_idea_content, IdeaGenerationError
from literature_radar.models import Paper, PaperAnalysis
from literature_radar.workflows import TaskStore, JobBusyError, ensure_collection, collection_state


def sample_result(sources):
    return {'title':'Two-paper combination','ideas':[dict(title='A testable transfer hypothesis',
        question='Can the representations transfer?',hypothesis='Transfer may improve the held-out result; this is untested.',
        combination='Combine the measurement in one paper with the method in the other.',
        experiment='Compare transferred features with an untrained baseline on held-out data.',
        evaluation='Compare held-out accuracy; no improvement would falsify the hypothesis.',
        risks='Abstract evidence does not establish that the proposed transfer will work.',
        novelty_checks='Search for prior cross-domain transfer and compare matching baselines.',
        evidence=[dict(paper_id=s['paper_id'],quote=s['title'],supports='The supplied title identifies an input research topic.') for s in sources[:2]])]}


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LibraryTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store;self.deck=DiscoveryDeck(self.store);self.tasks=TaskStore(self.store)
        self.store.upsert_paper(Paper(source='pubmed',external_id='second',title='A graph model for cell interactions',
            abstract='The model represents interactions between cells and evaluates held-out samples.',url='https://example.org',
            analysis=PaperAnalysis(provider='deepseek',score=25)))

    def wait(self,job):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            latest=self.tasks.get(job['id'])
            if latest['status']!='running':return latest
            time.sleep(.01)
        self.fail('Background task did not finish')

    def owned(self):
        self.deck.draw(5,str(uuid.uuid4()),ai_only=False)
        return self.deck.inventory()['cards']

    def post(self,path,data):
        port=self.fixture.start_server();conn=HTTPConnection('127.0.0.1',port,timeout=5);self.addCleanup(conn.close)
        conn.request('POST',path,urlencode(data),{'Content-Type':'application/x-www-form-urlencoded'})
        response=conn.getresponse();return response.status,json.loads(response.read())

    def test_warehouse_survives_rounds_and_retries(self):
        request_id=str(uuid.uuid4());self.deck.draw(5,request_id,ai_only=False)
        self.deck.draw(5,request_id,ai_only=False)
        self.assertEqual([c['draw_count'] for c in self.deck.inventory()['cards']],[1,1])
        self.deck.reset();self.assertEqual(self.deck.inventory()['stats']['total'],2)
        self.deck.draw(5,str(uuid.uuid4()),ai_only=False)
        self.assertEqual([c['draw_count'] for c in self.deck.inventory()['cards']],[2,2])

    def test_historical_batches_migrate_once(self):
        self.owned()
        with self.store._connect() as conn:
            conn.execute('DROP TABLE card_inventory');conn.execute("DELETE FROM discovery_meta WHERE key='inventory_migrated'")
        self.deck=DiscoveryDeck(self.store)
        self.assertEqual(self.deck.inventory()['total'],2)
        self.deck=DiscoveryDeck(self.store)
        self.assertEqual([c['draw_count'] for c in self.deck.inventory()['cards']],[1,1])

    def test_inventory_filters_and_notes(self):
        cards=self.owned();card=cards[0]
        self.store.update_user_fields(card['id'],favorite=True,user_note='独立样本',read_status='reading')
        result=self.deck.inventory(query='独立样本',favorite=True,status='reading',page=999)
        self.assertEqual(result['total'],1);self.assertEqual(result['page'],1)
        self.assertEqual(self.deck.inventory(tier='SSR')['total'],1)
        self.assertEqual(self.deck.inventory(tier='UNRATED')['total'],1)
        self.assertNotIn('user_note',result['cards'][0])

    def test_selection_requires_owned_distinct_papers(self):
        with self.assertRaises(ValueError):self.deck.owned_cards([self.fixture.paper_id])
        cards=self.owned()
        with self.assertRaises(ValueError):self.deck.owned_cards([cards[0]['id']]*2)
        duplicate=copy.deepcopy(cards);duplicate[1]['doi']=duplicate[0]['doi']='10.1234/same'
        with self.assertRaises(ValueError):source_snapshots(duplicate)

    def test_collector_counts_new_rows_and_preserves_notes(self):
        config=copy.deepcopy(self.fixture.config)
        for source in config['sources'].values():source['enabled']=False
        config['sources']['pubmed']['enabled']=True;config['run']['min_score']=0
        self.store.update_user_fields(self.fixture.paper_id,user_note='Keep this note',favorite=True)
        new=Paper(source='pubmed',external_id='new-source',title='Newly collected study',abstract='A new study abstract.',url='')
        with patch('literature_radar.collector.fetch_pubmed',return_value=[self.fixture.paper,new]), \
             patch('literature_radar.collector.analyze_paper',return_value=PaperAnalysis(provider='deepseek',score=25)), \
             patch('literature_radar.collector.write_html_report'),patch('literature_radar.collector.write_markdown_report'):
            result=collect_library(config,self.fixture.root)
        self.assertEqual(result['added'],1);self.assertEqual(result['matched'],2)
        self.assertEqual(self.store.list_for_library(query='Spatial atlas')[0]['user_note'],'Keep this note')

    def test_daily_collection_is_reused_and_partial_is_visible(self):
        calls=[]
        def collect(config,root,emit):
            calls.append(1);emit('source progress');return dict(added=1,matched=2,total=3,sources_failed=['arxiv'])
        with patch('literature_radar.workflows.collect_library',side_effect=collect):
            first=ensure_collection(self.tasks,self.fixture.config,self.fixture.root)
            job=self.wait(first['job']);self.assertEqual(job['status'],'partial')
            second=ensure_collection(self.tasks,self.fixture.config,self.fixture.root)
        self.assertTrue(second['fresh']);self.assertEqual(len(calls),1)
        self.assertIn('source progress',second['job']['log'])

    def test_failed_collection_never_counts_as_fresh(self):
        with patch('literature_radar.workflows.collect_library',side_effect=RuntimeError('secret-in-error')):
            first=ensure_collection(self.tasks,self.fixture.config,self.fixture.root)
            job=self.wait(first['job'])
        self.assertEqual(job['status'],'failed');self.assertFalse(collection_state(self.tasks,self.fixture.config)['fresh'])
        self.assertNotIn('secret-in-error',job['error'])

    def test_job_idempotence_and_conflicting_generation(self):
        release=threading.Event();calls=[]
        def work(emit):calls.append(1);release.wait(5);return {'title':'saved'}
        request_id=str(uuid.uuid4());job=self.tasks.start('ideas',{'ids':[1,2]},work,request_id)
        try:
            self.assertEqual(self.tasks.start('ideas',{'ids':[1,2]},work,request_id)['id'],job['id'])
            with self.assertRaises(JobBusyError):self.tasks.start('ideas',{'ids':[1,3]},work)
        finally:release.set();done=self.wait(job)
        self.assertEqual(done['status'],'succeeded');self.assertEqual(len(calls),1)
        self.assertEqual(TaskStore(self.store).get(job['id'])['result']['title'],'saved')

    def test_abandoned_task_is_recoverable(self):
        now=time.time()-90
        with self.store._connect() as conn:
            conn.execute('INSERT INTO workflow_jobs(id,kind,status,options_json,started,heartbeat) VALUES (?,?,?,?,?,?)',
                         ('abandoned','ideas','running','{}',now,now))
        self.assertEqual(self.tasks.get('abandoned')['status'],'interrupted')

    def test_ideas_validate_exact_quotes_and_cross_paper_support(self):
        sources=source_snapshots(self.owned());result=sample_result(sources)
        self.assertEqual(len(validate_result(result,sources)['ideas']),1)
        bad=copy.deepcopy(result);bad['ideas'][0]['evidence'][0]['quote']='A fabricated finding not stated anywhere'
        with self.assertRaises(ValueError):validate_result(bad,sources)
        bad=copy.deepcopy(result);bad['ideas'][0]['evidence'][0]['paper_id']=999
        with self.assertRaises(ValueError):validate_result(bad,sources)
        bad=copy.deepcopy(result);bad['ideas'][0]['evidence'][1]=bad['ideas'][0]['evidence'][0]
        with self.assertRaises(ValueError):validate_result(bad,sources)

    def test_model_payload_excludes_notes_and_returns_source_snapshots(self):
        self.store.update_user_fields(self.fixture.paper_id,user_note='PRIVATE_NOTE_DO_NOT_SEND')
        sources=source_snapshots(self.owned());config=copy.deepcopy(self.fixture.config)
        config.setdefault('analysis',{}).setdefault('deepseek',{})['enabled']=True
        response={'choices':[{'message':{'content':json.dumps(sample_result(sources))}}]}
        with patch('literature_radar.ideation.get_secret',return_value='test-key'),patch('literature_radar.ideation.request') as request:
            request.return_value.json.return_value=response
            result=generate_ideas(config,sources,'A research question',lambda _:None)
        payload=request.call_args.kwargs['json']
        self.assertNotIn('PRIVATE_NOTE_DO_NOT_SEND',json.dumps(payload))
        self.assertEqual(result['sources'],sources);self.assertFalse(result['novelty_verified'])
        self.assertEqual(request.call_args.kwargs['retry_total'],0)

    def test_json_compatibility_preserves_quoted_evidence(self):
        value={'text':'An exact quote with ,} and ,] plus "quoted" words.'}
        payload=json.dumps(value)
        self.assertEqual(decode_idea_content('```json\n'+payload[:-1]+',}\n```'),value)
        self.assertEqual(decode_idea_content('{"text":"first\nsecond"}'),{'text':'first\nsecond'})
        for bad in ['{"title":"unfinished', 'not JSON', '']:
            with self.assertRaises(IdeaGenerationError):decode_idea_content(bad)

    def test_truncated_output_is_specific_and_never_retried(self):
        sources=source_snapshots(self.owned());config=copy.deepcopy(self.fixture.config)
        config['analysis']['deepseek']['enabled']=True
        with patch('literature_radar.ideation.get_secret',return_value='test-key'),patch('literature_radar.ideation.request') as request:
            request.return_value.json.return_value={'choices':[{'finish_reason':'length','message':{'content':'{"title":"partial'}}]}
            job=self.wait(self.tasks.start('ideas',{},lambda emit:generate_ideas(config,sources,'',emit)))
        self.assertEqual(job['result']['error_code'],'output_truncated')
        self.assertEqual(job['status'],'failed');self.assertEqual(request.call_count,1)
        self.assertNotIn('partial',json.dumps(job));self.assertNotIn('test-key',json.dumps(job))

    def test_provider_failures_have_safe_actionable_codes(self):
        from requests import Response
        from requests.exceptions import HTTPError, Timeout, ConnectionError
        failures=[(Timeout('secret body'),'timeout'),(ConnectionError('secret body'),'connection')]
        for status,code in [(401,'authentication'),(402,'balance'),(404,'model_unavailable'),(429,'rate_limit'),(503,'provider_error')]:
            response=Response();response.status_code=status
            failures.append((HTTPError('secret body',response=response),code))
        for exc,code in failures:
            def fail(emit):raise exc
            job=self.wait(self.tasks.start('ideas',{},fail))
            self.assertEqual(job['result']['error_code'],code)
            self.assertNotIn('secret body',json.dumps(job))

    def test_malformed_response_and_evidence_remain_distinct(self):
        sources=source_snapshots(self.owned());config=copy.deepcopy(self.fixture.config)
        config['analysis']['deepseek']['enabled']=True
        invalid=sample_result(sources);invalid['ideas'][0]['evidence'][0]['quote']='Fabricated evidence never in source'
        for content,code in [('not valid JSON','invalid_json'),(json.dumps(invalid),'evidence_mismatch'),('', 'empty_response')]:
            with patch('literature_radar.ideation.get_secret',return_value='test-key'),patch('literature_radar.ideation.request') as request:
                request.return_value.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':content}}]}
                with self.assertRaises(IdeaGenerationError) as error:generate_ideas(config,sources,'',lambda _:None)
            self.assertEqual(error.exception.code,code)


    def test_generation_endpoint_uses_warehouse_and_persists(self):
        cards=self.owned();self.fixture.config['analysis']['deepseek']['enabled']=True
        def fake_generate(config,sources,question,emit):return {**sample_result(sources),'sources':sources,'question':question}
        with patch('literature_radar.ideation.get_secret',return_value='test-key'),patch('web_app.generate_ideas',side_effect=fake_generate):
            status,data=self.post('/api/ideas',{'paper_ids':','.join(str(c['id']) for c in cards),'question':'Combine these','request_id':str(uuid.uuid4())})
            self.assertEqual(status,200);job=self.wait(data['job'])
        self.assertEqual(job['status'],'succeeded');self.assertEqual(len(job['result']['sources']),2)
        status,_=self.post('/api/ideas',{'paper_ids':str(cards[0]['id'])});self.assertEqual(status,400)


if __name__=='__main__':unittest.main()