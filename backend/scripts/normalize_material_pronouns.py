"""Apply the reviewed corpus user-label migration, with a recoverable backup."""
import copy
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domains.persona.corpus_pronouns import normalize_excerpt, normalize_narration
from domains.persona.character_corpus import CharacterCorpusStore
from domains.persona.reviewed_material import SOURCE
from domains.memory.store import tokens


def main():
    root = SOURCE.parents[2]
    db = root / 'backend/cognition.db'
    backup = root / 'output' / ('corpus_pronouns_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup.mkdir(parents=True)
    original = SOURCE.read_bytes()
    document = json.loads(original)
    before = copy.deepcopy(document)
    fields = ['title', 'situation', 'retrieval_summary', 'observed_response',
              'interpretation', 'applicable_situation', 'response_pattern', 'story_context']
    for entry in document['entries']:
        for field in fields:
            if field in entry:
                entry[field] = normalize_narration(entry[field])
        for field in ['query_document', 'supporting_query_document']:
            entry['retrieval'][field] = normalize_narration(entry['retrieval'][field])
        for excerpt in entry['excerpts']:
            excerpt['text'] = normalize_excerpt(excerpt['text'])
    document['rules']['pronouns'] = '叙述和说话人标记中的用户指当前用户，左然为角色；台词中的第一人称按说话人理解。'
    with sqlite3.connect(db) as connection:
        rows = connection.execute('SELECT id,payload FROM character_corpus_v2').fetchall()
        (backup / 'database_records.json').write_text(json.dumps(dict(rows), ensure_ascii=False, indent=2), encoding='utf-8')
    (backup / SOURCE.name).write_bytes(original)
    # Validate every original quotation and every normalized excerpt before live writes.
    stage = backup / 'normalized.json'
    stage.write_text(json.dumps(document, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary = CharacterCorpusStore(str(backup / 'validation.db'))
    result = temporary.import_reviewed_material(stage)
    with sqlite3.connect(backup / 'validation.db') as c:
        converted = dict(c.execute('SELECT id,payload FROM character_corpus_v2'))
    assert set(converted) == {key for key, _ in rows}
    changed = 0
    with sqlite3.connect(db, timeout=30) as connection:
        for identity, raw in rows:
            old = json.loads(raw)
            new = json.loads(converted[identity])
            assert old['evidence_quote'] == new['evidence_quote']
            if old == new:
                continue
            changed += 1
            connection.execute('UPDATE character_corpus_v2 SET payload=? WHERE id=?', (converted[identity], identity))
            search = CharacterCorpusStore._embedding_text(new)+' '+new['story_context']+' '+new['observed_response']
            connection.execute('UPDATE character_corpus_v2_fts SET search_text=? WHERE id=?', (' '.join(sorted(tokens(search))), identity))
            if CharacterCorpusStore._embedding_text(old) != CharacterCorpusStore._embedding_text(new):
                connection.execute('DELETE FROM character_corpus_v2_embeddings WHERE id=?', (identity,))
        SOURCE.write_text(json.dumps(document, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(result, changed_records=changed, backup=str(backup)), ensure_ascii=False))


if __name__ == '__main__':
    main()
