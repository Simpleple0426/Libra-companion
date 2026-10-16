"""Offline, backed-up retirement of D2A scores; historical receipts stay intact."""
import argparse
from contextlib import closing
from datetime import datetime
import json
import sqlite3
from infrastructure.paths import PROJECT_ROOT,RUNTIME_ROOT
from life_prototype.config import canonical,digest
from life_prototype.state_schema import facts_only,current_state
from scripts.import_home_catalog import stopped_worker

MARKER='facts_only_state_v1'


def migrate(db):
    if db.execute('SELECT 1 FROM life_state WHERE name=?',(MARKER,)).fetchone():return {'already_migrated':True}
    before=json.loads(db.execute("SELECT body FROM life_state WHERE name='current'").fetchone()[0])
    state=current_state(before);state['revision']+=1
    for key in ('reading','viewing','activities','commitments','work_sessions','meal_plans','laundry_batches'):
        if state.get(key)!=before.get(key):raise ValueError('activity progress changed: '+key)
    db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    for name in ('cognition','interaction'):
        row=db.execute('SELECT body FROM life_state WHERE name=?',(name,)).fetchone()
        if row:db.execute('UPDATE life_state SET body=? WHERE name=?',(canonical(facts_only(json.loads(row[0]))),name))
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'life_time_meta' in tables:
        # Scoring clock is retired. Activity/sleep heartbeats own actual timing.
        db.execute('DELETE FROM life_time_meta')
    replaced=[]
    if {'life_scheduler_jobs','life_scheduler_recoveries'}<=tables:
        rows=db.execute("SELECT id,kind,payload FROM life_scheduler_jobs WHERE status!='done' AND kind IN ('decision','sync','agent_message') AND id NOT IN (SELECT blocked_job_id FROM life_scheduler_recoveries)").fetchall()
        for ident,kind,payload in rows:
            replacement='p4:facts-only:'+digest(ident)[:24]
            review='retire-needs:'+ident
            receipt={'replacement_job_id':replacement,'prior_job_id':ident,'reason':'D2A score contract retired; re-evaluate actual state'}
            db.execute("INSERT INTO life_scheduler_jobs VALUES(?,?,?,'pending',0,NULL,NULL)",(replacement,kind,payload))
            db.execute('INSERT INTO life_scheduler_recoveries VALUES(?,?,?,?,?)',(review,ident,replacement,canonical({'reason':'user_requested_remove_D2A_scores'}),canonical(receipt)))
            replaced.append(ident)
    row=db.execute("SELECT body FROM life_state WHERE name='scheduler'").fetchone()
    if row:
        meta=json.loads(row[0]);meta.update(dirty=True,next_decision=state['as_of'])
        db.execute("UPDATE life_state SET body=? WHERE name='scheduler'",(canonical(meta),))
    report={'removed_current_scores':'needs' in before,'replaced_jobs':replaced,'state_revision':state['revision']}
    db.execute('INSERT INTO life_state VALUES(?,1,?)',(MARKER,canonical(report)))
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    path=(RUNTIME_ROOT/'life/local-life-v1/prototype.sqlite3').resolve(strict=True)
    if not path.is_relative_to(PROJECT_ROOT.resolve()):raise ValueError('database outside project')
    if not args.apply:
        with closing(sqlite3.connect(path)) as db:
            state=json.loads(db.execute("SELECT body FROM life_state WHERE name='current'").fetchone()[0])
            print(json.dumps({'has_scores':'needs' in state,'revision':state['revision']}));return
    with stopped_worker(path.parent):
        backup=PROJECT_ROOT/'backups'/('facts-only-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
        backup.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db,closing(sqlite3.connect(backup/path.name)) as copy:
            db.backup(copy)
            with db:
                db.execute('BEGIN IMMEDIATE');report=migrate(db)
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('integrity check failed')
        print(json.dumps({'backup':str(backup),**report}))


if __name__=='__main__':main()
