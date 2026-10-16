"""Import the user-reviewed event document without re-indexing rejected source text."""
import hashlib
import json
from pathlib import Path

from domains.memory.store import tokens

PROJECT = Path(__file__).resolve().parents[3]
REVIEWED_SOURCE = PROJECT / 'libra/shared_history_review/共同经历候选.json'


def import_events(store, source):
    document = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    if document.get('schema_version') != 2 or not document.get('detail_review_complete'):
        raise ValueError('Shared history must be reviewed before import')
    events = document['entries']
    if not events or len({e['id'] for e in events}) != len(events):
        raise ValueError('Empty or duplicate reviewed events')
    records, chunks = [], []
    source_cache = {}
    stages = {'个人线': '告白前', '挚爱篇': '同居后', '相守篇': '结婚后'}
    for event in events:
        if event.get('detail_review_status') != 'reviewed_by_user':
            raise ValueError('Unreviewed event: ' + event['id'])
        stage = event['relationship_stage']
        path = event['source_ref']['path']
        if stage != next((v for k, v in stages.items() if k in Path(path).parts), None):
            raise ValueError('Invalid source stage: ' + event['id'])
        ids = []
        for excerpt in event['excerpts']:
            if excerpt['event_id'] != event['id'] or excerpt['source_path'] != path:
                raise ValueError('Excerpt belongs to another event')
            if path not in source_cache:
                source_path = (PROJECT / path).resolve()
                if not source_path.is_relative_to(PROJECT / 'libra'):
                    raise ValueError('Source outside libra')
                source_cache[path] = (hashlib.sha256(source_path.read_bytes()).hexdigest(),
                                      source_path.read_text(encoding='utf-8-sig').splitlines())
            digest, lines = source_cache[path]
            a, b = excerpt['line_start'], excerpt['line_end']
            if (digest != excerpt['source_sha256'] or not 1 <= a <= b <= len(lines)
                    or '\n'.join(lines[a-1:b]) != excerpt['text']):
                raise ValueError('Source excerpt changed: ' + event['id'])
            for start in range(a, b + 1, 25):
                end = min(start + 24, b)
                chunk_id = f"{excerpt['excerpt_id']}-L{start}"
                ids.append(chunk_id)
                chunks.append((chunk_id, path, start, end, '\n'.join(lines[start-1:end])))
        payload = {
            'history_id': event['id'], 'status': 'canonical_shared_past',
            'participants': ['user', 'zuoran'], 'title': event['title'],
            'summary': event['retrieval_summary'], 'detailed_event': event['detailed_event'],
            'relationship_stage': stage, 'temporal_scope': 'past_unspecified_date',
            'stage_scope': event['relationship_stage_scope'],
            'source_ref': event['source_ref'], 'excerpt_ids': ids,
        }
        searchable = ' '.join([payload['title'], payload['summary'], *payload['detailed_event']])
        records.append((payload, ' '.join(sorted(tokens(searchable)))))
    if len({c[0] for c in chunks}) != len(chunks):
        raise ValueError('Duplicate source chunks')
    store.initialize()
    with store.connect() as connection:
        for table in ('canonical_shared_history', 'canonical_shared_history_fts',
                      'canonical_shared_history_chunks', 'canonical_shared_history_chunks_fts'):
            connection.execute(f'DELETE FROM {table}')
        for payload, search_text in records:
            connection.execute('INSERT INTO canonical_shared_history VALUES (?,?,?,?,?,?,?)',
                (payload['history_id'], payload['relationship_stage'], payload['summary'],
                 payload['source_ref']['path'], None, None, json.dumps(payload, ensure_ascii=False)))
            connection.execute('INSERT INTO canonical_shared_history_fts VALUES (?,?)',
                               (payload['history_id'], search_text))
        connection.executemany('INSERT INTO canonical_shared_history_chunks VALUES (?,?,?,?,?)', chunks)
        # Source chunks are fetched only through the selected event IDs.
        connection.execute('DELETE FROM canonical_shared_history_chunk_embeddings')
        connection.execute('DELETE FROM canonical_shared_history_embeddings WHERE history_id NOT IN '
                           '(SELECT history_id FROM canonical_shared_history)')
    return {'records': len(records), 'chunks': len(chunks), 'source': str(source)}


def event_excerpts(store, scenes, query):
    result = []
    query_tokens = tokens(query)
    with store.connect() as connection:
        for scene in scenes:
            candidates = []
            for identity in scene.get('excerpt_ids', []):
                row = connection.execute('SELECT * FROM canonical_shared_history_chunks WHERE chunk_id=?',
                                         (identity,)).fetchone()
                if row:
                    item = dict(row)
                    item['history_id'] = scene['history_id']
                    candidates.append(item)
            candidates.sort(key=lambda x: len(query_tokens & tokens(x['content'])), reverse=True)
            result.extend(candidates[:2])
    return result
