"""认知功能配置和原始经历时间线。"""
import json
from .base import ValidationError, dumps

DEFAULT_FEATURES = {'cognition': True}

def features(store):
    with store.connect() as c:
        row = c.execute("SELECT value FROM memory_config WHERE key='features'").fetchone()
    saved = json.loads(row[0]) if row else {}
    return {key: saved.get(key, default) for key, default in DEFAULT_FEATURES.items()}

def set_features(store, values):
    if set(values) - set(DEFAULT_FEATURES) or any(type(v) is not bool for v in values.values()):
        raise ValidationError('invalid_features')
    config = features(store)
    config.update(values)
    with store.connect(True) as c:
        c.execute("INSERT INTO memory_config VALUES ('features',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (dumps(config),))
    return config

def guidance(store, current_text):
    """Explicit current risk boundaries, without reviving derived personality rules."""
    from .lmc import active_rows
    with store.connect() as c:
        return [{'memory_id':r['memory_id'],'type':'boundary','content':r['content'],
                 'priority':0,'external_action':None}
                for r in active_rows(store,c)
                if r['category']=='risk_boundary' and r['sensitivity']=='normal'][:4]

def timeline(store, story_memory_id=None, limit=100):
    with store.connect() as c:
        episodes = [dict(r) for r in c.execute("""SELECT m.memory_id,m.title,m.content,e.occurred_start,e.episode_phase,x.thread,x.category
            FROM lmc_memories m JOIN lmc_event_context e USING(memory_id)
            JOIN lmc_memory_coordinates x USING(memory_id)
            WHERE m.record_status='active' AND x.status='current'
            AND (? IS NULL OR x.thread=?) ORDER BY e.occurred_start DESC LIMIT ?""",
            (story_memory_id,story_memory_id,max(1, min(limit, 200))))]
        ids = {r['memory_id'] for r in episodes}
        links = [dict(r) for r in c.execute("SELECT * FROM lmc_memory_relations WHERE status='active'")
                 if r['source_id'] in ids and r['target_id'] in ids]
    return {'episodes': list(reversed(episodes)), 'links': links, 'open_loops': []}
