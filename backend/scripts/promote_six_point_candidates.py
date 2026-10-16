"""One-time, evidence-validated promotion of retained six-point candidates."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domains.memory.store import MemoryStore, ValidationError
from domains.memory.base import utc
from infrastructure.paths import COGNITION_DATABASE_PATH, BACKUP_ROOT


def run(apply=False):
    store = MemoryStore(COGNITION_DATABASE_PATH)
    with store.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM lmc_candidates WHERE importance=6 AND memory_id IS NULL AND decision='rejected' AND reason='importance' ORDER BY occurred_at")]
        store.fts_available = bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='lmc_fts'").fetchone())
    if not apply:
        return {'eligible': len(rows), 'candidate_ids': [r['candidate_id'] for r in rows]}
    backup = BACKUP_ROOT / ('before-six-point-promotion-' + utc().replace(':', '-') + '.db')
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(COGNITION_DATABASE_PATH) as source, sqlite3.connect(backup) as dest:
        source.backup(dest)
    results = []
    with store.connect(True) as c:
        for row in rows:
            current = c.execute('SELECT memory_id FROM lmc_candidates WHERE candidate_id=?', (row['candidate_id'],)).fetchone()
            if current['memory_id']:
                continue
            c.execute('SAVEPOINT promotion')
            try:
                proposal = json.loads(row['proposal_json'])
                if proposal['importance'] != 6:
                    raise ValidationError('importance_mismatch')
                ids = json.loads(row['source_ids_json'])
                raws = {}
                for sid in ids:
                    raw = c.execute('SELECT * FROM raw_experiences WHERE experience_id=?', (sid,)).fetchone()
                    if not raw or raw['source_status'] != 'active':
                        raise ValidationError('inactive_source')
                    if c.execute("SELECT 1 FROM lmc_sources s JOIN lmc_memories m USING(memory_id) JOIN lmc_memory_coordinates x USING(memory_id) WHERE s.experience_id=? AND (m.record_status!='active' OR x.status!='current')", (sid,)).fetchone():
                        raise ValidationError('superseded_source_owner')
                    raws[sid] = dict(raw)
                result = store._write_candidate(c, proposal, raws, utc())
                if result.get('memory_id'):
                    c.execute('UPDATE lmc_candidates SET decision=?,reason=?,memory_id=? WHERE candidate_id=?',
                              (result['decision'], result['reason'], result['memory_id'], row['candidate_id']))
                    c.execute("UPDATE experience_segments SET segment_state='processed' WHERE segment_id=?", (row['segment_id'],))
                # Preserve original extraction receipts; the report records this
                # administrative promotion and memory revisions record provenance.
                results.append({'candidate_id': row['candidate_id'], 'scope': row['primary_scope'], **result})
            except ValidationError as error:
                c.execute('ROLLBACK TO promotion')
                results.append({'candidate_id': row['candidate_id'], 'skipped': str(error)})
            finally:
                c.execute('RELEASE promotion')
    report = {'backup': str(backup), 'results': results}
    backup.with_suffix('.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    print(json.dumps(run(parser.parse_args().apply), ensure_ascii=True))
