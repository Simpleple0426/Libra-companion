"""Apply reviewed shared history and verify local lexical/semantic recall."""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domains.persona.canonical_history import CanonicalHistoryStore
from domains.persona.reviewed_history import REVIEWED_SOURCE
from infrastructure.embeddings.local import get_local_embedding_adapter
from infrastructure.paths import COGNITION_DATABASE_PATH


def main():
    store = CanonicalHistoryStore(COGNITION_DATABASE_PATH, get_local_embedding_adapter())
    store.initialize()
    archive = REVIEWED_SOURCE.parent / '导入存档'
    archive.mkdir(exist_ok=True)
    tables = ['canonical_shared_history', 'canonical_shared_history_fts',
              'canonical_shared_history_chunks', 'canonical_shared_history_chunks_fts',
              'canonical_shared_history_embeddings', 'canonical_shared_history_chunk_embeddings']
    with store.connect() as connection:
        previous = {t: [dict(r) for r in connection.execute(f'SELECT * FROM {t}')] for t in tables}
    backup = archive / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
    backup.write_text(json.dumps(previous, ensure_ascii=False), encoding='utf-8')
    report = store.import_reviewed()
    print(json.dumps(report, ensure_ascii=False), flush=True)
    report['embeddings'] = store.refresh_embeddings(batch_size=16)
    report['smoke_recall'] = {}
    for query in ['被误认成夫妻', '琥珀袖扣', '邂逅博物馆']:
        matches = store.search(query, limit=3)
        if not matches:
            raise RuntimeError('Recall failed: ' + query)
        report['smoke_recall'][query] = [{'id': x['history_id'], 'stage': x['relationship_stage']}
                                         for x in matches]
    with store.connect() as connection:
        report['table_counts'] = {t: connection.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables}
        stages = connection.execute('SELECT relationship_stage FROM canonical_shared_history').fetchall()
    report['stages'] = dict(Counter(r[0] for r in stages))
    report['database'] = str(COGNITION_DATABASE_PATH)
    report['backup'] = str(backup)
    report['stage_filter_enabled'] = False
    report['event_bound_excerpts'] = True
    (REVIEWED_SOURCE.parent / '入库校验.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
