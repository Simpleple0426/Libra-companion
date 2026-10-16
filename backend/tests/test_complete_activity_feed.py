import sqlite3
import json
import unittest
from datetime import date, datetime, timedelta

from life_prototype.activity_feed import read


class CompleteActivityFeedTests(unittest.TestCase):
    def test_housework_display_combines_tool_steps_without_changing_delivery_facts(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            for i, title in enumerate(['取用抹布', '擦拭茶几', '放回抹布']):
                db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',
                           (str(i), f'2026-10-10T19:{10+i*3}:00+08:00', '左然开始'+title,
                            'housework_start', str(i), 'tidy-slot', str(i)))
            display = read(db, {}, {}, limit=None)
            self.assertEqual([item['event'] for item in display], ['左然开始收拾家里'])
            self.assertEqual(display[0]['occurred_at'], '2026-10-10T19:10:00+08:00')
            self.assertEqual(len(read(db, {}, {}, limit=None, collapse_consecutive=False)), 3)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 3)

    def test_consecutive_identical_activity_keeps_first_but_preserves_changes(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            descriptions = ['左然正在陪用户看电影', '左然正在陪用户看电影',
                            '陪伴已结束', '左然正在陪用户看电影',
                            '左然正在陪用户看电影', '左然正在陪伴用户']
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?)', [
                (str(i), f'2026-09-30T{20+i//4:02d}:{i%4*10:02d}:00+08:00', text,
                 'companion_update', None, None, None)
                for i, text in enumerate(descriptions)])
            events = read(db, {}, {}, schedule_date=date(2026, 9, 30), limit=None)
            self.assertEqual([e['id'] for e in events], ['0', '2', '3', '5'])
            self.assertEqual([e['id'] for e in read(db, {}, {}, limit=2)], ['3', '5'])
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 6)

    def test_companion_receipt_does_not_break_feed_or_become_agenda_change(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            db.execute('CREATE TABLE life_agenda_messages (message_id TEXT, status TEXT, receipt TEXT)')
            at = '2026-09-30T17:53:00+08:00'
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',
                       ('departure', at, '左然离开了忒弥斯律所', 'moving_start', None, 'commute', None))
            receipts = [
                {'status': 'applied', 'companion_proposal': {}, 'companion': {}},
                {'status': 'applied', 'companion_proposal': {}, 'at': at},
                {'status': 'applied'},
                {'at': 'invalid'},
                {'at': at, 'schedule_changed': True},
            ]
            db.executemany('INSERT INTO life_agenda_messages VALUES (?,?,?)',
                           [(str(i), 'applied', json.dumps(value)) for i, value in enumerate(receipts)])
            events = read(db, {}, {}, schedule_date=date(2026, 9, 30), limit=None)
            self.assertEqual([event['id'] for event in events], ['departure', 'agenda-review:4'])

    def test_real_home_departure_and_later_room_arrival_remain_distinct(self):
        from life_prototype.event_store import describe
        config = {'places': {'home': {'name': '家'}, 'home.f2.bedroom': {'name': '卧室'}}}
        activity = {'id': 'move', 'kind': 'moving', 'route': ['home', 'city'], 'target': 'city'}
        state = {'activities': {'move': activity}}
        fact = describe('leave', {'operation': 'start', 'payload': {'activity_id': 'move'}}, {}, state, config)
        self.assertEqual(fact[1:], ('moving_start', '左然离开了家'))
        activity.update(route=['city', 'home', 'home.f2.bedroom'], target='home.f2.bedroom', status='completed')
        fact = describe('room', {'operation': 'result', 'activity_id': 'move',
            'evidence': {'from': 'home', 'to': 'home.f2.bedroom'}}, {}, state, config)
        self.assertEqual(fact[1:], ('arrived', '左然正在卧室'))

    def test_home_boundary_is_shown_before_room_arrival_even_if_route_failed(self):
        from life_prototype.event_store import describe
        config = {'places': {'home': {'name': '家'}, 'home.f2.bedroom': {'name': '卧室'}}}
        state = {'activities': {
            'outside': {'id': 'outside', 'kind': 'moving', 'route': ['city', 'home', 'home.f2.bedroom'],
                        'target': 'home.f2.bedroom', 'status': 'failed'},
            'inside': {'id': 'inside', 'kind': 'moving', 'route': ['home', 'home.f2.bedroom'],
                       'target': 'home.f2.bedroom', 'status': 'running'}}}
        request = {'operation': 'result', 'activity_id': 'outside', 'evidence': {'from': 'city', 'to': 'home'}}
        receipt = {'occurred_at': '2026-09-29T22:35:40+08:00', 'source': 'simulated_world'}
        fact = describe('arrival', request, receipt, state, config)
        self.assertEqual(fact[1:], ('arrived', '左然回到了家'))
        self.assertIsNone(describe('start', {'operation': 'start', 'payload': {'activity_id': 'inside'}}, {}, state, config))
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            db.execute('CREATE TABLE life_receipts(category TEXT,id TEXT,request TEXT,receipt TEXT)')
            db.execute('INSERT INTO life_receipts VALUES(?,?,?,?)', ('event_control', 'arrival', json.dumps(request), json.dumps(receipt)))
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?)', ('wrong', '2026-09-29T22:43:07+08:00', '左然离开了家', 'moving_start', 'inside', None, None))
            events = read(db, state, config, schedule_date=date(2026, 9, 29), limit=None)
            self.assertEqual([(e['occurred_at'], e['event']) for e in events], [(receipt['occurred_at'], '左然回到了家')])
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?)', ('arrival', receipt['occurred_at'], '左然回到了家', 'arrived', 'outside', None, None))
            self.assertEqual(len(read(db, state, config, limit=None)), 1)

    def test_full_day_is_not_truncated_and_uses_four_am_boundary(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            start = datetime.fromisoformat('2026-09-28T04:00:00+08:00')
            rows = [(str(i), (start + timedelta(seconds=i)).isoformat(), f'事件{i}',
                     'work_start', None, None, None) for i in range(600)]
            rows += [('late', '2026-09-29T03:59:59+08:00', '凌晨事件', 'ended', None, None, None),
                     ('next', '2026-09-29T04:00:00+08:00', '次日事件', 'work_start', None, None, None)]
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?)', rows)
            events = read(db, {}, {}, schedule_date=date(2026, 9, 28), limit=None)
            self.assertEqual(len(events), 600)
            self.assertEqual(events[0]['id'], '0')
            self.assertEqual(events[-1]['id'], '599')
            self.assertEqual(len(read(db, {}, {}, schedule_date=date(2026, 9, 28))), 200)

    def test_only_activity_beginnings_and_sleep_boundaries_are_visible(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            at = '2026-09-28T08:00:00+08:00'
            rows = [
                ('start', at, '左然开始工作', 'work_start', 'a', 'c', 'f'),
                ('pause', at, '左然暂时放下工作', 'work_end', 'a', 'c', 'f'),
                ('resume', at, '左然继续工作', 'work_resume', 'a', 'c', 'f'),
                ('progress', at, '工作进度', 'work_progress', 'a', 'c', 'f'),
                ('wake', at, '左然起床了', 'woke', None, None, None),
            ]
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?)', rows)
            events = read(db, {}, {}, schedule_date=date(2026, 9, 28), limit=None)
            self.assertEqual([event['id'] for event in events], ['start', 'wake'])

    def test_retired_four_am_wake_bug_displays_confirmed_workday_wake(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            db.execute('CREATE TABLE life_daily_agendas (day TEXT, revision INTEGER, body TEXT)')
            db.execute('INSERT INTO life_daily_agendas VALUES (?,?,?)', (
                '2026-09-30', 2,
                json.dumps({'calendar': {'day_type': 'workday'}}, ensure_ascii=False),
            ))
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?)', [
                ('room', '2026-09-30T04:00:04+08:00', '左然正在卧室', 'at_place', None, 'morning', None),
                ('bath', '2026-09-30T04:00:10+08:00', '左然正在二层卫生间', 'at_place', None, 'morning', None),
                ('brush', '2026-09-30T04:00:44+08:00', '左然正在刷牙', 'care_start', 'care', 'morning', None),
                ('breakfast', '2026-09-30T07:30:00+08:00', '左然正在餐厅', 'at_place', None, 'breakfast', None),
            ])
            config = {'display_timezone': 'Asia/Shanghai', 'places': {
                'home.f2.bedroom': {'name': '卧室'},
                'home.f2.bathroom': {'name': '二层卫生间'},
                'home.f1.dining': {'name': '餐厅'},
            }}
            events = read(db, {}, config, schedule_date=date(2026, 9, 30), limit=None)
            self.assertEqual([(event['occurred_at'], event['event']) for event in events], [
                ('2026-09-30T07:00:00+08:00', '左然起床了'),
                ('2026-09-30T07:30:00+08:00', '左然正在餐厅'),
            ])

    def test_restarted_route_shows_one_departure_until_arrival(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            rows = [
                ('leave-1', '2026-09-29T08:15:00+08:00', '左然离开了家',
                 'moving_start', 'move-1', 'commute-1', None),
                ('leave-2', '2026-09-29T08:37:00+08:00', '左然离开了家',
                 'moving_start', 'move-2', 'commute-2', None),
                ('arrive', '2026-09-29T09:01:00+08:00', '左然到达了翟星办公室',
                 'arrived', 'move-2', 'commute-2', None),
            ]
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?)', rows)
            events = read(db, {}, {}, schedule_date=date(2026, 9, 29), limit=None)
            self.assertEqual([event['id'] for event in events], ['leave-1', 'arrive'])

    def test_arrival_from_outside_firm_uses_firm_boundary(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                       'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',
                       ('arrive', '2026-09-29T09:01:00+08:00', '左然到达了翟星办公室',
                        'arrived', 'move', 'work', None))
            state = {'activities': {'move': {
                'route': ['home', 'city.dining_access', 'firm', 'firm.zhai_office'],
                'target': 'firm.zhai_office',
            }}}
            config = {'places': {'firm': {'name': '忒弥斯律所'}}}
            events = read(db, state, config, schedule_date=date(2026, 9, 29), limit=None)
            self.assertEqual([event['event'] for event in events], [
                '左然到达了忒弥斯律所',
                '左然到达了翟星办公室',
            ])
