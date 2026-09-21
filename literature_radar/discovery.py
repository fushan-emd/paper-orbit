"""Persistent, non-repeating literature draws based on real stored AI scores."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from literature_radar.library_ui import safe_source_url
from literature_radar.storage import PaperStore
from literature_radar.identity import publication_kind

TIERS = ((28, 'UR'), (24, 'SSR'), (18, 'SR'), (10, 'R'), (0, 'N'))
POOLS = {'unread', 'to_read', 'all'}
AI_CONDITION = """(CASE WHEN json_valid(p.analysis_json)
    THEN json_extract(p.analysis_json, '$.provider') END = 'deepseek'
    AND typeof(p.score) = 'integer' AND p.score BETWEEN 0 AND 30)"""


def object_json(value):
    try:
        parsed = json.loads(value or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def rarity(score, provider: str) -> str:
    if provider != 'deepseek' or type(score) is not int or not 0 <= score <= 30:
        return 'UNRATED'
    return next(tier for threshold, tier in TIERS if score >= threshold)


def serialize_card(row) -> dict:
    analysis = object_json(row['analysis_json'])
    tier = rarity(row['score'], analysis.get('provider', ''))
    try:
        tags = json.loads(row['tags_json'] or '[]')
    except (ValueError, TypeError):
        tags = []
    return {
        'id': row['id'], 'title': row['title'], 'source': row['source'],
        'journal': row['journal'] or '', 'published': row['published'] or '',
        'doi': row['doi'] or '', 'url': safe_source_url(row['url'] or ''),
        'abstract': row['abstract'] or '', 'score': row['score'] if tier != 'UNRATED' else None,
        'publication_kind':analysis.get('publication_kind',publication_kind(row['source'])), 'retraction_status':analysis.get('retraction_status','not_checked'),
        'rarity': tier, 'tags': [str(t) for t in tags[:4]] if isinstance(tags, list) else [],
        'analysis': analysis, 'favorite': bool(row['favorite']), 'read_status': row['read_status'],
    }


class DiscoveryDeck:
    def __init__(self, store: PaperStore):
        self.store = store
        with store._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS discovery_seen (
                paper_id INTEGER PRIMARY KEY, seen_at TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS discovery_batches (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, pool TEXT NOT NULL,
                query TEXT NOT NULL, ai_only INTEGER NOT NULL, requested INTEGER NOT NULL,
                paper_ids_json TEXT NOT NULL)''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_discovery_created ON discovery_batches(created_at)')
            conn.execute('''CREATE TABLE IF NOT EXISTS card_inventory (
                paper_id INTEGER PRIMARY KEY, first_drawn TEXT NOT NULL,
                last_drawn TEXT NOT NULL, draw_count INTEGER NOT NULL DEFAULT 1)''')
            conn.execute('CREATE TABLE IF NOT EXISTS discovery_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            if not conn.execute("SELECT 1 FROM discovery_meta WHERE key='inventory_migrated'").fetchone():
                conn.execute('''INSERT OR IGNORE INTO card_inventory
                    SELECT p.id, MIN(b.created_at), MAX(b.created_at), COUNT(*)
                    FROM discovery_batches b, json_each(CASE WHEN json_valid(b.paper_ids_json) THEN b.paper_ids_json ELSE '[]' END) j
                    JOIN papers p ON p.id = j.value GROUP BY p.id''')
                conn.execute("INSERT OR IGNORE INTO discovery_meta VALUES ('inventory_migrated','1')")

    @staticmethod
    def _filter(pool: str, query: str, ai_only: bool, unseen: bool = True):
        if pool not in POOLS:
            raise ValueError('Unknown card pool')
        if len(query) > 300:
            raise ValueError('Search is too long')
        where, params = PaperStore._library_filters(query, False, '', 0, '')
        clauses = [where, "p.read_status != 'ignore'", "(p.doi_key='' OR p.id=(SELECT MIN(d.id) FROM papers d WHERE d.doi_key=p.doi_key))"]
        clauses.append("COALESCE(CASE WHEN json_valid(p.analysis_json) THEN json_extract(p.analysis_json,'$.retraction_status') END,'not_checked') NOT IN ('retracted','retraction_notice')")
        if pool == 'unread':
            clauses.append("p.read_status IN ('new', 'to_read')")
        elif pool == 'to_read':
            clauses.append("p.read_status = 'to_read'")
        if ai_only:
            clauses.append(AI_CONDITION)
        if unseen:
            clauses.append("NOT EXISTS (SELECT 1 FROM discovery_seen s WHERE s.paper_id=p.id)")
            clauses.append("(p.doi_key='' OR NOT EXISTS (SELECT 1 FROM papers seen_p JOIN discovery_seen s ON s.paper_id=seen_p.id WHERE seen_p.doi_key=p.doi_key))")
        return ' AND '.join(clauses), params

    def summary(self, pool='unread', query='', ai_only=True) -> dict:
        where, params = self._filter(pool, query, ai_only)
        with self.store._connect() as conn:
            rows = conn.execute(f'SELECT p.score, p.analysis_json FROM papers p WHERE {where}', params).fetchall()
            seen = conn.execute('SELECT COUNT(*) FROM discovery_seen s JOIN papers p ON p.id = s.paper_id').fetchone()[0]
            all_where, all_params = self._filter(pool, query, False, unseen=False)
            total = conn.execute(f'SELECT COUNT(*) FROM papers p WHERE {all_where}', all_params).fetchone()[0]
        tiers = {tier: 0 for _, tier in reversed(TIERS)}
        tiers['UNRATED'] = 0
        for row in rows:
            tiers[rarity(row['score'], object_json(row['analysis_json']).get('provider', ''))] += 1
        return {'remaining': len(rows), 'seen': seen, 'pool_total': total, 'tiers': tiers}

    @staticmethod
    def _batch(conn, batch) -> dict:
        ids = json.loads(batch['paper_ids_json'])
        cards = []
        for paper_id in ids:
            row = conn.execute('SELECT * FROM papers WHERE id = ?', (paper_id,)).fetchone()
            if row is not None:
                cards.append(serialize_card(row))
        return {'id': batch['id'], 'created_at': batch['created_at'], 'pool': batch['pool'],
                'query': batch['query'], 'ai_only': bool(batch['ai_only']),
                'requested': batch['requested'], 'cards': cards}

    def latest(self):
        with self.store._connect() as conn:
            row = conn.execute('SELECT * FROM discovery_batches ORDER BY created_at DESC, rowid DESC LIMIT 1').fetchone()
            return self._batch(conn, row) if row else None

    def draw(self, count: int, request_id: str, pool='unread', query='', ai_only=True) -> dict:
        if type(count) is not int or count not in {1, 5, 10}:
            raise ValueError('Draw count must be 1, 5 or 10')
        request_id = str(uuid.UUID(request_id))
        where, params = self._filter(pool, query, ai_only)
        with self.store._connect() as conn:
            # Reserve cards atomically, including across multiple application windows.
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT * FROM discovery_batches WHERE id = ?', (request_id,)).fetchone()
            if existing:
                if (existing['pool'], existing['query'], bool(existing['ai_only']), existing['requested']) != (pool, query, ai_only, count):
                    raise ValueError('Request ID already used with different draw options')
                return self._batch(conn, existing)
            rows = conn.execute(f'SELECT p.id FROM papers p WHERE {where} ORDER BY RANDOM() LIMIT ?', [*params, count]).fetchall()
            ids = [r['id'] for r in rows]
            now = datetime.now(UTC).isoformat(timespec='microseconds')
            conn.executemany('INSERT INTO discovery_seen(paper_id, seen_at) VALUES (?, ?)', [(paper_id, now) for paper_id in ids])
            conn.executemany('''INSERT INTO card_inventory(paper_id,first_drawn,last_drawn,draw_count) VALUES (?,?,?,1)
                ON CONFLICT(paper_id) DO UPDATE SET last_drawn=excluded.last_drawn,draw_count=card_inventory.draw_count+1''',
                [(paper_id,now,now) for paper_id in ids])
            conn.execute('INSERT INTO discovery_batches VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (request_id, now, pool, query, int(ai_only), count, json.dumps(ids)))
            return self._batch(conn, conn.execute('SELECT * FROM discovery_batches WHERE id = ?', (request_id,)).fetchone())

    def reset(self):
        # Only discovery history for the current round is reset; library fields are untouched.
        with self.store._connect() as conn:
            conn.execute('DELETE FROM discovery_seen')

    def act(self, paper_id: int, action: str) -> dict:
        if action == 'favorite':
            self.store.update_user_fields(paper_id, favorite=True)
        elif action == 'unfavorite':
            self.store.update_user_fields(paper_id, favorite=False)
        elif action == 'to_read':
            # Adding to a queue must not downgrade a paper already read or being reproduced.
            with self.store._connect() as conn:
                result = conn.execute("""UPDATE papers SET
                    read_status = CASE WHEN read_status IN ('new', 'ignore') THEN 'to_read' ELSE read_status END,
                    updated_at = ? WHERE id = ?""", (datetime.now(UTC).replace(tzinfo=None).isoformat(timespec='seconds'), paper_id))
                if not result.rowcount:
                    raise LookupError('Paper not found')
        else:
            raise ValueError('Unknown card action')
        with self.store._connect() as conn:
            row = conn.execute('SELECT * FROM papers WHERE id = ?', (paper_id,)).fetchone()
            if row is None:
                raise LookupError('Paper not found')
            return serialize_card(row)
    def inventory(self, query='', favorite=False, tier='', status='', page=1, page_size=20):
        if len(query)>300 or tier not in {'','N','R','SR','SSR','UR','UNRATED'}:
            raise ValueError('Invalid warehouse filter')
        where,params=PaperStore._library_filters(query,favorite,status,0,'')
        clauses=[where]
        if tier:
            if tier=='UNRATED':
                clauses.append(f'NOT COALESCE({AI_CONDITION},0)')
            else:
                low,high={'N':(0,9),'R':(10,17),'SR':(18,23),'SSR':(24,27),'UR':(28,30)}[tier]
                clauses.extend([AI_CONDITION,'p.score BETWEEN ? AND ?']);params.extend([low,high])
        where=' AND '.join(clauses)
        page_size=max(1,min(page_size,100))
        with self.store._connect() as conn:
            total=conn.execute(f'SELECT COUNT(*) FROM card_inventory i JOIN papers p ON p.id=i.paper_id WHERE {where}',params).fetchone()[0]
            pages=max(1,(total+page_size-1)//page_size);page=min(pages,max(1,page))
            rows=conn.execute(f"""SELECT p.*,i.first_drawn,i.last_drawn,i.draw_count
                FROM card_inventory i JOIN papers p ON p.id=i.paper_id WHERE {where}
                ORDER BY i.last_drawn DESC,p.id DESC LIMIT ? OFFSET ?""",[*params,page_size,(page-1)*page_size]).fetchall()
            stats=conn.execute("""SELECT COUNT(*) total,COALESCE(SUM(p.favorite),0) favorites,
                COALESCE(SUM(p.read_status='to_read'),0) to_read
                FROM card_inventory i JOIN papers p ON p.id=i.paper_id""").fetchone()
        cards=[]
        for row in rows:
            card=serialize_card(row)
            card.update(first_drawn=row['first_drawn'],last_drawn=row['last_drawn'],draw_count=row['draw_count'])
            cards.append(card)
        return dict(cards=cards,total=total,page=page,pages=pages,stats=dict(stats))

    def owned_cards(self,ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=6 or any(type(i) is not int or i<=0 for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('Choose 1 to 6 different owned cards')
        cards=[]
        with self.store._connect() as conn:
            for paper_id in ids:
                row=conn.execute('SELECT p.* FROM card_inventory i JOIN papers p ON p.id=i.paper_id WHERE p.id=?',(paper_id,)).fetchone()
                if row is None:raise ValueError('Choose cards already in your warehouse')
                cards.append(serialize_card(row))
        return cards
