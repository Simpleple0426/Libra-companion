import unittest
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from life_prototype.leisure_thoughts import enqueue, _process


class LeisureThoughtOwnershipTests(unittest.TestCase):
    def test_system_address_is_retried_without_displaying_a_draft(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE life_leisure_thought_jobs(id TEXT PRIMARY KEY,status TEXT,attempts INTEGER,retry_at TEXT,body TEXT)')
            body={'activity_id':'shopping:1','skill':'shopping','subject':'购物',
                  'place':'shop','started_at':'2026-10-04T10:00:00+00:00'}
            db.execute('INSERT INTO life_leisure_thought_jobs VALUES(?,?,?,?,?)',
                       ('thought:1','pending',0,None,json.dumps(body)))
            cog=Mock()
            cog.store.connect.return_value=db
            cog.clock.now.return_value=datetime(2026,10,4,10,10,tzinfo=timezone.utc)
            cog.calls.ask.return_value={'body':'以后可以和用户一起挑选。'}
            _process(cog,'thought:1')
            self.assertEqual(db.execute('SELECT status FROM life_leisure_thought_jobs').fetchone()[0],'retry')
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='life_dynamic_drafts'").fetchone())

    def test_short_activity_does_not_enqueue(self):
        cog=Mock();cog.clock.now.return_value=datetime(2026,9,29,12,tzinfo=timezone.utc)
        activity={'id':'reading:1','status':'running','place':'home.f2.study',
                  'started_at':(cog.clock.now.return_value-timedelta(minutes=4)).isoformat()}
        enqueue(cog,activity,skill='reading',subject='阅读《局外人》')
        cog.store.connect.assert_not_called()

    def test_non_running_activity_does_not_enqueue(self):
        cog=Mock()
        enqueue(cog,{'status':'completed'},skill='movie',subject='观看电影')
        cog.store.connect.assert_not_called()


if __name__=='__main__':unittest.main()
