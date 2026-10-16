"""Evidence-backed extraction candidates, retained independently of promotion."""
from .base import *
from .lmc import evidence, number, CATEGORIES


def meaningful(raw):
    # Filter machine telemetry by provenance, never a user's discussion of it.
    if raw['source_type'] == 'chat_message':
        return True
    if raw['source_type'] == 'state_snapshot':
        return False
    return not re.search(r'^(左然生活状态更新|用户生活动态报告|设备状态更新)\s*[:：]', raw['content'])


def retain(c, job, index, proposal, raws, now):
    if not isinstance(proposal, dict) or proposal.get('type') not in CATEGORIES:
        raise ValidationError('invalid_candidate_type')
    importance = number(proposal.get('importance'), 'importance', 1, 10)
    confidence = number(proposal.get('confidence'), 'confidence')
    if importance != int(importance):
        raise ValidationError('invalid_importance')
    scope = proposal.get('primary_scope')
    if scope not in {'user', 'self', 'shared'}:
        raise ValidationError('invalid_scope')
    title = proposal.get('title')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 240:
        raise ValidationError('invalid_title')
    sources, content = evidence(c, proposal.get('claims'), raws, scope)
    if any(not meaningful(raw) for raw, _ in sources):
        return None
    cid = 'candidate:' + job['job_id'] + ':' + str(index)
    sensitivity = 'sensitive' if SENSITIVE.search(content) or any(SENSITIVE.search(r['content']) for r, _ in sources) else 'normal'
    c.execute('''INSERT INTO lmc_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (cid, job['job_id'], job['segment_id'], index, title, content, scope,
               int(importance), confidence, sensitivity, dumps(proposal),
               dumps([r['experience_id'] for r, _ in sources]),
               min(r['occurred_at'] for r, _ in sources), now, 'pending', '', None))
    return cid


def search(c, queries, pending, recent_ids, recent_text, scopes, sensitivity):
    hits = []
    for row in c.execute("SELECT * FROM lmc_candidates WHERE memory_id IS NULL AND decision='rejected' AND reason='importance'"):
        p = json.loads(row['proposal_json'])
        if (row['primary_scope'] not in scopes or row['sensitivity'] not in sensitivity
                or row['confidence'] < .6 or p.get('risk') != 'normal'
                or p.get('fact_status', 'current') != 'current'
                or row['content'] in recent_text
                or any(overlap(q, row['content']) > .15 for q in pending)):
            continue
        ids = json.loads(row['source_ids_json'])
        sources = [c.execute('SELECT * FROM raw_experiences WHERE experience_id=?', (sid,)).fetchone() for sid in ids]
        if not sources or any(not r or r['source_status'] != 'active' or not meaningful(r) for r in sources):
            continue
        try:
            evidence(c, p['claims'], {r['experience_id']: r for r in sources}, row['primary_scope'])
        except ValidationError:
            continue
        if any(str(r['source_id']) in recent_ids for r in sources):
            continue
        # An invalidated/superseded owner must not reappear through candidates.
        if any(c.execute('''SELECT 1 FROM lmc_sources s JOIN lmc_memories m USING(memory_id)
                  JOIN lmc_memory_coordinates x USING(memory_id)
                  WHERE s.experience_id=? AND (m.record_status!='active' OR x.status!='current')''', (sid,)).fetchone() for sid in ids):
            continue
        key = p.get('fact_key')
        if key and c.execute("SELECT 1 FROM lmc_memory_coordinates WHERE fact_key=? AND status='current'", (row['primary_scope'] + ':' + key.strip(),)).fetchone():
            continue
        score = max(overlap(q, row['title'] + ' ' + row['content']) for q in queries)
        if score >= .3:
            hits.append((score, dict(row)))
    return sorted(hits, key=lambda hit: (hit[0], hit[1]['occurred_at']), reverse=True)
