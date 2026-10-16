import json
from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
import unittest
import test_meal_skill as fixture
from scripts.retire_schedule_data import clean_app,clean_life,OLD_TABLES
from life_prototype.config import canonical


class RetirementTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp

    def test_app_cleanup_removes_only_retired_rows(self):
        path=self.root/'old.db'
        with closing(sqlite3.connect(path)) as db, db:
            for table in OLD_TABLES:
                db.execute('CREATE TABLE '+table+'(id INTEGER)');db.execute('INSERT INTO '+table+' VALUES(1)')
            db.execute('CREATE TABLE app_settings(key TEXT,value TEXT)')
            db.executemany('INSERT INTO app_settings VALUES(?,?)',[('libra_schedule_v2:day','old'),('user_preference','keep')])
            db.execute('CREATE TABLE messages(id INTEGER,content TEXT)');db.execute("INSERT INTO messages VALUES(1,'keep')")
        self.assertEqual(clean_app(path)['libra_state_events'],1)
        clean_app(path,True)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM libra_state_events').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT content FROM messages').fetchone()[0],'keep')
            self.assertEqual(db.execute('SELECT key FROM app_settings').fetchone()[0],'user_preference')

    def test_life_cleanup_preserves_progress_and_user_arrangements(self):
        from life_prototype.scheduler import Scheduler,DEFAULTS
        from life_prototype.fine_plan import initialize
        Scheduler(self.chat,DEFAULTS);initialize(self.p.store)
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['reading']={'book:version':400};state['viewing']={'movie':300}
            state['commitments']=[{'id':'user-promise','status':'confirmed'}]
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
            user={'appointments':[{'id':'appointment'}],'cancelled':[]}
            body={'items':[{'old':'plan'}],'user_constraints':user}
            db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)',('2026-09-28',7,canonical(body)))
            db.execute("INSERT INTO life_fine_agendas VALUES('old','parent','ready',1,'{}')")
            db.execute("INSERT INTO life_fine_execution VALUES('activity','block','parent','end')")
            clean_life(db)
            after=self.p.store.read(db)
            for key in ('reading','viewing','commitments'):self.assertEqual(after[key],state[key])
            saved=json.loads(db.execute('SELECT body FROM life_daily_agendas').fetchone()[0])
            self.assertEqual(saved['revision'],7);self.assertEqual(saved['items'],[])
            self.assertEqual(saved['user_constraints'],user)
            self.assertEqual(db.execute('SELECT count(*) FROM life_fine_agendas').fetchone()[0],0)
            self.assertTrue(clean_life(db)['already_migrated'])


if __name__=='__main__':unittest.main()
