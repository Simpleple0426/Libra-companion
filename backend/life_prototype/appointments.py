"""Durable future intentions, independent of generated daily agendas."""
from copy import deepcopy
import json

from .clock import utc
from .config import canonical, digest


def display_title(title):
    title = title.strip()
    for prefix in ('左然正在', '左然', '正在'):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    for prefix in ('陪老婆', '陪我', '陪你', '和用户一起', '和我一起', '和你一起'):
        if title.startswith(prefix):
            return '陪用户' + title[len(prefix):]
    if title.startswith('陪'):
        return title
    return '陪用户' + title.removeprefix('一起')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS life_appointments(
        id TEXT PRIMARY KEY, start_at TEXT NOT NULL, end_at TEXT NOT NULL,
        status TEXT NOT NULL, body TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS life_appointments_upcoming ON life_appointments(status,end_at)')
    # Adopt accepted legacy appointments once; cancelled rows are retained so
    # subsequent starts cannot resurrect them from an older agenda revision.
    for raw, in db.execute('''SELECT a.body FROM life_daily_agendas a WHERE revision=(
        SELECT MAX(b.revision) FROM life_daily_agendas b WHERE b.day=a.day)''').fetchall():
        for item in json.loads(raw).get('user_constraints', {}).get('appointments', []):
            db.execute('INSERT OR IGNORE INTO life_appointments VALUES(?,?,?,?,?)',
                       (item['id'], utc(item['start_at']).isoformat(), utc(item['end_at']).isoformat(),
                        'planned', canonical(item)))


def upcoming(db, now):
    return [json.loads(r[0]) for r in db.execute('''SELECT body FROM life_appointments
        WHERE status='planned' AND end_at>? ORDER BY start_at,id''', (utc(now).isoformat(),))]


def version(items):
    return digest(items)


def for_day(rules, day):
    from .coarse_plan import schedule_day
    result = deepcopy(rules)
    result['appointments'] = [a for a in rules['appointments'] if schedule_day(utc(a['start_at'])) == day]
    return result


def save(db, before, after):
    keep = {a['id'] for a in after}
    for item in before:
        if item['id'] not in keep:
            db.execute("UPDATE life_appointments SET status='cancelled' WHERE id=?", (item['id'],))
    for item in after:
        db.execute('''INSERT INTO life_appointments VALUES(?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET start_at=excluded.start_at,end_at=excluded.end_at,
                status=excluded.status,body=excluded.body''',
                   (item['id'], utc(item['start_at']).isoformat(), utc(item['end_at']).isoformat(),
                    'planned', canonical(item)))


def validate_future(agenda, rules, now, state, new_ids):
    """Feasibility preview only: never persist future activities or observations."""
    from .coarse_plan import schedule_day, _at, generate, RULES_PATH
    from .coarse_plan_updates import reflow
    from .daily_obligations import day_fact
    days = {schedule_day(utc(a['start_at'])) for a in rules['appointments']
            if a['id'] in new_ids and schedule_day(utc(a['start_at'])) > schedule_day(now)}
    for day in sorted(days):
        at = _at(day, '04:00')
        preview = deepcopy(state)
        preview.update(place=agenda.p.config['initial']['place'], activities={}, meals={})
        body = generate(agenda.p.config, preview, at, day_fact(_at(day, '12:00'), agenda.cog.calendar_provider),
                        json.loads(RULES_PATH.read_text(encoding='utf8')))
        reflow(body, for_day({'cancelled': [], 'appointments': rules['appointments']}, day),
               preview, agenda.p.config, at)
