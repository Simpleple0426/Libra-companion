"""Immutable reading copies of successful daily Dream passes, with live evidence checks."""
import json
from datetime import date, datetime, timedelta

from .base import dumps, utc


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS lmc_dream_entries (
        entry_id TEXT PRIMARY KEY, page_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')


def capture(c, entry_id, page):
    if page['period_type'] == 'day':
        c.execute('INSERT OR IGNORE INTO lmc_dream_entries VALUES (?,?,?,?)',
                  (entry_id, page['page_id'], dumps(dict(page)), page['generated_at']))


def reading(store, *, kind='reviews', offset=0, limit=30, on_date=None, level=None):
    from .dream import evidence, valid, LOCAL
    if kind not in ('reviews', 'dreams') or offset < 0 or not 1 <= limit <= 100:
        raise ValueError('invalid_reading_query')
    if level is not None and level not in ('day', 'week', 'month', 'quarter', 'year'):
        raise ValueError('invalid_reading_level')
    selected = date.fromisoformat(on_date) if on_date else None
    today = datetime.now(LOCAL).date().isoformat()
    with store.connect() as c:
        rows = evidence(c)
        if kind == 'dreams':
            records = ((r['entry_id'], json.loads(r['snapshot_json'])) for r in c.execute(
                'SELECT * FROM lmc_dream_entries ORDER BY created_at DESC,entry_id DESC'))
        else:
            records = ((r['page_id'], dict(r)) for r in c.execute(
                'SELECT * FROM lmc_dream_pages ORDER BY period_end DESC,period_start DESC,page_id'))
        result = []
        scopes = []
        for entry_id, page in records:
            if level and page['period_type'] != level:
                continue
            start = datetime.fromisoformat(utc(page['period_start'])).astimezone(LOCAL).date()
            end = datetime.fromisoformat(utc(page['period_end'])).astimezone(LOCAL).date()
            if selected and not start <= selected < end:
                continue
            sources = json.loads(page['sources_json'])
            available = bool(sources) and all(mid in rows and rows[mid]['revision'] == rev
                                             and rows[mid]['primary_scope'] == page['primary_scope']
                                             for mid, rev in sources.items())
            if kind == 'reviews' and not valid(page, rows):
                continue
            result.append(dict(id=entry_id, period_type=page['period_type'],
                               period_start=start.isoformat(), period_end=end.isoformat(),
                               display_end=(end - timedelta(days=1)).isoformat(),
                               generated_at=page['generated_at'], available=available,
                               content=page['content'] if available else '',
                               reflection=page['reflection'] if available else '',
                               scenes=json.loads(page['scenes_json']) if available else [],
                               foresight=[f for f in json.loads(page['foresight_json']) if f['valid_until'] >= today] if available else [],
                               complete_period=page['period_end'] <= utc()))
            # Reading clients don't need internal evidence identifiers.
            for scene in result[-1]['scenes']:
                scene.pop('source_ids', None)
            scopes.append(page['primary_scope'])
    if kind == 'reviews':
        grouped = {}
        for item, scope in zip(result, scopes):
            key = (item['period_type'], item['period_start'], item['period_end'])
            grouped.setdefault(key, {})[scope] = item
        combined = []
        labels = {'user': '你的经历', 'shared': '我们的片段', 'self': '他的经历'}
        for key, parts in grouped.items():
            values = sorted(parts.items(), key=lambda part: {'user': 0, 'shared': 1, 'self': 2}.get(part[0], 3))
            item = dict(values[0][1])
            item['id'] = 'review:' + ':'.join(key)
            item['generated_at'] = max(part['generated_at'] for _, part in values)
            for field in ('content', 'reflection'):
                sections, seen = [], set()
                for scope, part in values:
                    text = part[field].strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    sections.append((labels.get(scope, '这段时光') + '\n' if len(values) > 1 else '') + text)
                item[field] = '\n\n'.join(sections)
            for field in ('scenes', 'foresight'):
                item[field] = [entry for _, part in values for entry in part[field]]
            combined.append(item)
        result = combined
    return {'items': result[offset:offset + limit], 'has_more': len(result) > offset + limit,
            'offset': offset, 'timezone': 'Asia/Shanghai', 'day_start_hour': 4}
