from concurrent.futures import ThreadPoolExecutor
from test_library import HTTPConnection
import json
import unittest
from urllib.parse import urlencode
import uuid

import test_library as fixtures
from literature_radar.deepseek import _build_prompt, _merge_llm_json
from literature_radar.discovery import DiscoveryDeck, rarity
from literature_radar.discovery_ui import discovery_page
from literature_radar.models import Paper, PaperAnalysis


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LibraryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.deck = DiscoveryDeck(self.store)
        for i in range(30):
            self.store.upsert_paper(Paper(source='pubmed', external_id='draw-'+str(i),
                title=f'Discovery paper {i}', abstract='An abstract with <script>unsafe markup</script>',
                url='https://example.org/paper', analysis=PaperAnalysis(provider='deepseek',
                    score=[6,12,20,25,29][i%5], summary='Test evidence', why_read='Relevant to the research task.')))

    def draw(self, count=10, **kwargs):
        return self.deck.draw(count, str(uuid.uuid4()), **kwargs)

    def request(self, method, path, data=None):
        port = self.fixture.start_server()
        conn = HTTPConnection('127.0.0.1', port, timeout=5)
        self.addCleanup(conn.close)
        conn.request(method, path, urlencode(data) if data is not None else None,
                     {'Content-Type':'application/x-www-form-urlencoded'})
        response = conn.getresponse()
        body = response.read()
        return response.status, json.loads(body) if 'json' in response.getheader('Content-Type','') else body.decode('utf-8')

    def test_exact_tier_boundaries_and_unrated_fallback(self):
        for score, expected in [(0,'N'),(9,'N'),(10,'R'),(17,'R'),(18,'SR'),(23,'SR'),(24,'SSR'),(27,'SSR'),(28,'UR'),(30,'UR')]:
            self.assertEqual(rarity(score,'deepseek'),expected)
        for score in [-1,31,None,'28',True,28.5]:
            self.assertEqual(rarity(score,'deepseek'),'UNRATED')
        self.assertEqual(rarity(29,'heuristic:deepseek_error'),'UNRATED')

    def test_pool_counts_real_tiers_and_ai_only(self):
        summary = self.deck.summary()
        self.assertEqual(summary['remaining'],30)
        self.assertEqual(summary['tiers'],dict(N=6,R=6,SR=6,SSR=6,UR=6,UNRATED=0))
        self.assertEqual(self.deck.summary(ai_only=False)['remaining'],31)
        self.assertEqual(self.deck.summary(ai_only=False)['tiers']['UNRATED'],1)
        self.assertEqual(self.deck.summary(query='missing')['remaining'],0)

    def test_single_five_ten_and_last_partial_draw(self):
        cards=[]
        for count, expected in [(1,1),(5,5),(10,10),(10,10),(10,4),(1,0)]:
            batch=self.draw(count)
            self.assertEqual(len(batch['cards']),expected)
            cards.extend(c['id'] for c in batch['cards'])
        self.assertEqual(len(set(cards)),30)
        self.assertEqual(self.deck.summary()['remaining'],0)
        self.assertEqual(self.deck.summary()['seen'],30)

    def test_retry_is_idempotent_and_restores_after_reopen(self):
        request_id=str(uuid.uuid4())
        first=self.deck.draw(10,request_id)
        reopened=DiscoveryDeck(self.store)
        self.assertEqual(first,reopened.draw(10,request_id))
        self.assertEqual(first,reopened.latest())
        self.assertEqual(reopened.summary()['seen'],10)
        with self.assertRaises(ValueError):
            reopened.draw(5,request_id)
        self.assertEqual(reopened.summary()['remaining'],20)

    def test_concurrent_draws_never_duplicate(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            batches=list(executor.map(lambda _: self.draw(10), range(3)))
        ids=[c['id'] for b in batches for c in b['cards']]
        self.assertEqual(len(ids),30)
        self.assertEqual(len(set(ids)),30)

    def test_actions_and_reset_preserve_notes_and_completed_reading(self):
        card=self.draw(1)['cards'][0]
        self.store.update_user_fields(card['id'],user_note='Important private note',read_status='read')
        self.deck.act(card['id'],'favorite')
        self.deck.act(card['id'],'to_read')
        self.deck.reset()
        row=next(r for r in self.store.list_for_library() if r['id']==card['id'])
        self.assertEqual((row['favorite'],row['read_status'],row['user_note']),(1,'read','Important private note'))
        self.assertEqual(self.deck.summary(pool='all')['remaining'],30)
        self.assertEqual(self.deck.summary()['seen'],0)
        self.assertEqual(self.deck.latest()['cards'][0]['id'],card['id'])
        self.assertFalse(self.deck.act(card['id'],'unfavorite')['favorite'])

    def test_reading_pools_and_excluded_papers(self):
        ids=[r['id'] for r in self.store.list_for_library() if r['external_id'].startswith('draw-')]
        for paper_id,status in zip(ids[:4],['to_read','read','ignore','reading']):
            self.store.update_user_fields(paper_id,read_status=status)
        self.assertEqual(self.deck.summary()['remaining'],27)
        self.assertEqual(self.deck.summary(pool='to_read')['remaining'],1)
        self.assertEqual(self.deck.summary(pool='all')['remaining'],29)
        self.assertEqual(self.draw(1,pool='to_read')['cards'][0]['read_status'],'to_read')

    def test_invalid_requests_never_reserve_cards(self):
        for count in [0,2,11,-1]:
            with self.assertRaises(ValueError): self.draw(count)
        with self.assertRaises(ValueError): self.deck.draw(1,'not-a-uuid')
        with self.assertRaises(ValueError): self.draw(pool='bad')
        self.assertEqual(self.deck.summary()['seen'],0)

    def test_ai_score_validation_and_rubric_storage(self):
        for payload in [{'score':None},{'score':True},{'score':31},{'score':'UR'},[],{'summary':'missing score'}]:
            result=_merge_llm_json(PaperAnalysis(score=50),json.dumps(payload))
            self.assertEqual(result.provider,'heuristic:deepseek_bad_score')
        payload={'score':28,'rating_dimensions':dict(relevance=12,methods=8,evidence=5,reusability=3)}
        analysis=_merge_llm_json(PaperAnalysis(),json.dumps(payload))
        self.assertEqual(analysis.rating_dimensions,payload['rating_dimensions'])
        self.fixture.paper.analysis=analysis
        self.store.upsert_paper(self.fixture.paper)
        row=self.store.list_for_library(query='Spatial atlas')[0]
        self.assertEqual(json.loads(row['analysis_json'])['rating_dimensions'],payload['rating_dimensions'])
        payload['rating_dimensions']['relevance']=3
        self.assertEqual(_merge_llm_json(PaperAnalysis(),json.dumps(payload)).rating_dimensions,{})
        prompt=_build_prompt(self.fixture.paper,analysis,self.fixture.config)
        self.assertIn('relevance 0-12',prompt)
        self.assertIn('rating_dimensions',prompt)

    def test_pages_are_translated_and_assets_inlined(self):
        for lang,label in [('zh-CN','十连抽'),('en','Draw ten')]:
            html=discovery_page(lang)
            self.assertIn(label,html)
            self.assertIn('id="card-grid"',html)
            self.assertNotIn('__CSS__',html)
            self.assertNotIn('__JS__',html)
            self.assertNotRegex(html,r'\[\[[a-z_]+\]\]')
        status,html=self.request('GET','/discover')
        self.assertEqual(status,200)
        self.assertIn('PAPER',html)

    def test_draw_and_action_api(self):
        status,result=self.request('POST','/api/discovery/draw',dict(count=5,request_id=str(uuid.uuid4())))
        self.assertEqual(status,200)
        self.assertEqual(len(result['batch']['cards']),5)
        card=result['batch']['cards'][0]
        status,result=self.request('POST','/api/discovery/action',dict(paper_id=card['id'],action='favorite'))
        self.assertEqual(status,200)
        self.assertTrue(result['card']['favorite'])
        status,result=self.request('GET','/api/discovery?latest=1')
        self.assertEqual(status,200)
        self.assertEqual(len(result['batch']['cards']),5)
        self.assertEqual(result['summary']['remaining'],25)

    def test_invalid_reset_and_actions_do_not_mutate(self):
        self.draw(1)
        status,_=self.request('POST','/api/discovery/reset',dict(pool='bad'))
        self.assertEqual(status,400)
        self.assertEqual(self.deck.summary()['seen'],1)
        status,_=self.request('POST','/api/discovery/action',dict(paper_id=99999,action='favorite'))
        self.assertEqual(status,404)
        status,_=self.request('POST','/api/discovery/draw',dict(count=7,request_id=str(uuid.uuid4())))
        self.assertEqual(status,400)
        self.assertEqual(self.deck.summary()['seen'],1)


if __name__=='__main__':
    unittest.main()