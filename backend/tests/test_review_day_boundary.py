import ast
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from domains.memory.calendar import _period
from domains.memory.dream import valid
from domains.memory.dream_journal import reading


def test_period_changes_at_four_in_shanghai_for_day_and_month():
    before = datetime.fromisoformat('2026-10-01T03:59:59+08:00')
    after = datetime.fromisoformat('2026-10-01T04:00:00+08:00')
    assert _period(before, 'day')[0].startswith('2026-09-29T20:00:00')
    assert _period(after, 'day')[0].startswith('2026-09-30T20:00:00')
    assert _period(before, 'month')[0].startswith('2026-08-31T20:00:00')
    assert _period(after, 'month')[0].startswith('2026-09-30T20:00:00')
    assert _period(datetime.fromisoformat('2026-09-30T20:00:00Z'), 'day') == _period(after, 'day')


def test_reading_combines_scopes_before_pagination_and_filters_date(tmp_path):
    path = tmp_path / 'reading.db'
    sources = {}
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE lmc_dream_pages(page_id TEXT, period_type TEXT, period_start TEXT,
            period_end TEXT, primary_scope TEXT, signature TEXT, content TEXT, reflection TEXT,
            scenes_json TEXT, foresight_json TEXT, sources_json TEXT, children_json TEXT, generated_at TEXT)''')
        for day, scope in [(1, 'user'), (1, 'shared'), (2, 'user')]:
            start, end = _period(datetime.fromisoformat(f'2026-10-{day:02d}T12:00:00+08:00'), 'day')
            ident = f'{day}:{scope}'
            sources[ident] = {'revision': 1, 'primary_scope': scope, 'occurred_start': start}
            db.execute('INSERT INTO lmc_dream_pages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, 'day', start, end, scope, 'signature', ident, 'thought ' + ident,
                        '[]', '[]', json.dumps({ident: 1}), '{}', end))
    @contextmanager
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        try: yield db
        finally: db.close()
    store = SimpleNamespace(connect=connect)
    with patch('domains.memory.dream.evidence', return_value=sources):
        first = reading(store, limit=1)
        assert first['has_more'] and first['items'][0]['period_start'] == '2026-10-02'
        second = reading(store, limit=1, offset=1)
        assert not second['has_more'] and second['items'][0]['period_start'] == '2026-10-01'
        assert '1:user' in second['items'][0]['content'] and '1:shared' in second['items'][0]['content']
        selected = reading(store, on_date='2026-10-01')
        assert len(selected['items']) == 1 and selected['day_start_hour'] == 4


def test_old_midnight_page_is_not_mislabeled_as_four_am_day():
    page = {'period_type': 'day', 'period_start': '2026-09-30T16:00:00.000000+00:00',
            'period_end': '2026-10-01T16:00:00.000000+00:00'}
    assert not valid(page, {})


def test_diary_goodnight_boundary_is_four():
    tree = ast.parse((Path(__file__).parents[1] / 'app/runtime.py').read_text(encoding='utf8'))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_diary_period_for_goodnight')
    scope = dict(datetime=datetime, timedelta=timedelta)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'diary-boundary', 'exec'), scope)
    assert scope['_diary_period_for_goodnight'](datetime(2026, 10, 1, 3, 59))[0] == '2026-09-30'
    assert scope['_diary_period_for_goodnight'](datetime(2026, 10, 1, 4))[0] == '2026-10-01'
