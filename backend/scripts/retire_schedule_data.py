"""Explicit one-time retirement of generated schedules. Run with server stopped."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from infrastructure.paths import PROJECT_ROOT,DATABASE_PATH,CONTENT_DATABASE_PATH,COGNITION_DATABASE_PATH,RUNTIME_ROOT
from life_prototype.config import canonical,digest

OLD_TABLES=('libra_schedule_timeline_keys','libra_attribute_snapshots','libra_attribute_adjustments',
            'libra_attribute_effects','libra_state_events','libra_timeline_events')
MARKER='skill_schedule_migration_v4'


def counts(db,names):
    existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {name:db.execute('SELECT count(*) FROM "'+name+'"').fetchone()[0] for name in names if name in existing}


def clean_app(path,apply=False):
    with closing(sqlite3.connect(path)) as db, db:
        report=counts(db,OLD_TABLES)
        keys=[r[0] for r in db.execute('SELECT key FROM app_settings') if r[0].startswith('libra_schedule_')]
        report['settings']=len(keys)
        if not apply:return report
        db.execute('BEGIN IMMEDIATE')
        # Dependent projections of the retired schedule are removed first.
        existing=counts(db,('world_events','libra_thoughts'))
        if 'world_events' in existing:
            condition='source_timeline_event_id IS NOT NULL OR source_state_event_id IS NOT NULL'
            if 'libra_thoughts' in existing:
                db.execute('DELETE FROM libra_thoughts WHERE source_event_id IN (SELECT event_id FROM world_events WHERE '+condition+')')
            db.execute('DELETE FROM world_events WHERE '+condition)
        for name in report:
            if name!='settings':db.execute('DELETE FROM "'+name+'"')
        db.executemany('DELETE FROM app_settings WHERE key=?',[(k,) for k in keys])
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('app integrity failed')
        return report


def clean_life(db):
    """Caller holds the scheduler OS lock. Preserve executed facts and progress."""
    if db.execute('SELECT 1 FROM life_state WHERE name=?',(MARKER,)).fetchone():return {'already_migrated':True}
    state=json.loads(db.execute("SELECT body FROM life_state WHERE name='current'").fetchone()[0])
    protected={k:deepcopy(state.get(k)) for k in ('reading','viewing','work_steps','work_sessions','meal_plans','care_plans','laundry_batches','household_followups','commitments')}
    report=counts(db,('life_daily_agendas','life_fine_agendas','life_fine_execution'))
    latest={}
    if 'life_daily_agendas' in report:
        for day,revision,raw in db.execute('SELECT day,revision,body FROM life_daily_agendas ORDER BY revision'):
            latest[day]=(revision,json.loads(raw))
        db.execute('DELETE FROM life_daily_agendas')
        for day,(revision,old) in latest.items():
            # Preserve revision sequence and explicit user constraints, not old
            # generated rows; no new ID may alias an old executed activity.
            stub={'date':day,'revision':revision,'basis':'retired_schedule_cache','version':'skill-coarse-v4',
                'items':[],'past_items':[],'calendar':old.get('calendar',{}),'conflicts':[],
                'source':'migration_user_arrangements_only','user_constraints':old.get('user_constraints',{})}
            db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)',(day,revision,canonical(stub)))
    for table in ('life_fine_execution','life_fine_agendas'):
        if table in report:db.execute('DELETE FROM '+table)
    state.pop('coarse_state',None)
    for a in state.get('activities',{}).values():a.pop('reading_deadline',None)
    state['revision']+=1
    if any(state.get(k)!=v for k,v in protected.items()):raise RuntimeError('protected progress changed')
    db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    row=db.execute("SELECT body FROM life_state WHERE name='scheduler'").fetchone()
    if row:
        meta=json.loads(row[0]);meta.update(dirty=True,next_decision=state['as_of']);meta.pop('agenda_basis',None)
        db.execute("UPDATE life_state SET body=? WHERE name='scheduler'",(canonical(meta),))
    db.execute("UPDATE life_scheduler_jobs SET status='done',receipt=? WHERE kind='decision' AND status IN ('pending','running','blocked')",
        (canonical({'cancelled':'retired schedule cache; replan with skills; no activity result'}),))
    db.execute('INSERT INTO life_state(name,id,body) VALUES(?,1,?)',(MARKER,canonical(report)))
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    life=RUNTIME_ROOT/'life/local-life-v1/prototype.sqlite3'
    if not args.apply:
        with closing(sqlite3.connect(life)) as db:report=counts(db,('life_daily_agendas','life_fine_agendas','life_fine_execution'))
        print(json.dumps({'app':clean_app(DATABASE_PATH),'life':report}));return
    from application.local_life import open_persisted_engine
    from scripts.recover_life_job import NoGeneration
    from infrastructure.sqlite.database import get_work_calendar_day
    engine=open_persisted_engine(life.parent.parent,'local-life-v1',NoGeneration(),calendar_provider=get_work_calendar_day)
    # Acquire the actual worker lock before backup or mutation; a live server
    # makes this fail safely instead of racing the scheduler.
    with engine.worker():
        backup=PROJECT_ROOT/'backups'/('skill-schedule-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
        backup.mkdir(parents=True)
        for path in (DATABASE_PATH,CONTENT_DATABASE_PATH,COGNITION_DATABASE_PATH,life):
            resolved=path.resolve(strict=True)
            if not resolved.is_relative_to(PROJECT_ROOT.resolve()):raise RuntimeError('migration target outside workspace')
            with closing(sqlite3.connect(resolved)) as source,closing(sqlite3.connect(backup/path.name)) as destination:source.backup(destination)
        app_report=clean_app(DATABASE_PATH,True)
        with engine.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');life_report=clean_life(db)
        # Install catalogued places before rebuilding current intentions.
        from life_prototype.meal_places import install
        install(engine.cog)
        agenda=engine.cog.agenda.ensure()
        print(json.dumps({'backup':str(backup),'app_deleted_rows':app_report,'life_cleared_rows':life_report,
                          'new_source':agenda.get('source') if agenda else None},ensure_ascii=True))


if __name__=='__main__':main()
