"""Rebuildable calendar hierarchy and retrieval-resolution projection."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .store import content_fingerprint, dumps, overlap, utc


LEVELS = ('day', 'week', 'month', 'quarter', 'year')


def initialize(store):
    with store.connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS lmc_calendar_summaries (
            summary_id TEXT PRIMARY KEY,
            period_type TEXT NOT NULL CHECK(period_type IN ('day','week','month','quarter','year')),
            period_start TEXT NOT NULL, period_end TEXT NOT NULL,
            primary_scope TEXT NOT NULL CHECK(primary_scope IN ('user','self','shared')),
            summary TEXT NOT NULL, source_count INTEGER NOT NULL,
            source_signature TEXT NOT NULL, generated_at TEXT NOT NULL,
            UNIQUE(period_type,period_start,primary_scope)
        );
        CREATE INDEX IF NOT EXISTS idx_calendar_summary_lookup
            ON lmc_calendar_summaries(primary_scope,period_type,period_start,period_end);
        CREATE TABLE IF NOT EXISTS lmc_calendar_sources (
            summary_id TEXT NOT NULL REFERENCES lmc_calendar_summaries(summary_id) ON DELETE CASCADE,
            memory_id TEXT NOT NULL REFERENCES lmc_memories(memory_id),
            source_revision INTEGER NOT NULL,
            PRIMARY KEY(summary_id,memory_id)
        );
        CREATE INDEX IF NOT EXISTS idx_calendar_source_memory ON lmc_calendar_sources(memory_id);
        ''')
        c.commit()


def _period(moment: datetime, level: str):
    local=moment.astimezone(timezone(timedelta(hours=8)))
    day=(local-timedelta(hours=4)).replace(hour=4,minute=0,second=0,microsecond=0)
    if level=='day':start=day;end=start+timedelta(days=1)
    elif level=='week':start=day-timedelta(days=day.weekday());end=start+timedelta(days=7)
    elif level=='month':
        start=day.replace(day=1)
        end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
    elif level=='quarter':
        start=day.replace(month=((day.month-1)//3)*3+1,day=1)
        end=start.replace(year=start.year+1,month=1) if start.month==10 else start.replace(month=start.month+3)
    elif level=='year':start=day.replace(month=1,day=1);end=start.replace(year=start.year+1)
    else:raise ValueError('invalid_calendar_level')
    return utc(start),utc(end)


def _summary(rows, level):
    ordered=sorted(rows,key=lambda row:row['occurred_start'])
    maximum={'day':900,'week':760,'month':620,'quarter':520,'year':420}[level]
    lines=[]
    for row in ordered:
        date=str(row['occurred_start'])[:10]
        text=' '.join(str(row['content']).split())
        line=f"{date} {text}"
        if line not in lines:lines.append(line)
    prefix={'day':'当日','week':'本周','month':'本月','quarter':'本季度','year':'本年'}[level]
    body='；'.join(lines)
    if len(body)>maximum:body=body[:maximum-1]+'…'
    return f'{prefix}记忆概览：{body}'


def refresh(store):
    """Refresh all affected periods only when authoritative LMC state changes."""
    with store.connect() as c:
        rows=[dict(row) for row in c.execute('''SELECT m.memory_id,m.revision,m.primary_scope,m.content,
            m.record_status,e.occurred_start FROM lmc_memories m
            JOIN lmc_event_context e USING(memory_id)
            JOIN lmc_memory_coordinates x USING(memory_id)
            WHERE x.status='current' AND x.active_fact=1 AND x.source_revision=m.revision AND m.sensitivity='normal'
            AND EXISTS (SELECT 1 FROM lmc_sources s JOIN raw_experiences r USING(experience_id)
                        WHERE s.memory_id=m.memory_id AND r.source_status='active')
            AND NOT EXISTS (SELECT 1 FROM lmc_sources s JOIN raw_experiences r USING(experience_id)
                            WHERE s.memory_id=m.memory_id AND r.source_status!='active')
            ORDER BY m.memory_id''')]
        previous=c.execute("SELECT value FROM memory_config WHERE key='calendar_summary_signature'").fetchone()
    signature=hashlib.sha256(('Asia/Shanghai-day-start-04-v2'+dumps([(r['memory_id'],r['revision'],r['record_status'],r['occurred_start']) for r in rows])).encode()).hexdigest()
    if previous and previous[0]==signature:return 0
    eligible=[r for r in rows if r['record_status']=='active']
    groups={}
    for row in eligible:
        try:moment=datetime.fromisoformat(str(row['occurred_start']).replace('Z','+00:00'))
        except ValueError:continue
        for level in LEVELS:
            start,end=_period(moment,level)
            groups.setdefault((level,start,end,row['primary_scope']),[]).append(row)
    now=utc();records=[]
    for (level,start,end,scope),members in groups.items():
        source_sig=hashlib.sha256(dumps([(m['memory_id'],m['revision']) for m in members]).encode()).hexdigest()
        summary_id='cal_'+hashlib.sha256(f'{level}|{start}|{scope}'.encode()).hexdigest()[:24]
        records.append((summary_id,level,start,end,scope,_summary(members,level),len(members),source_sig,now,members))
    with store.connect(True) as c:
        c.execute('DELETE FROM lmc_calendar_sources')
        c.execute('DELETE FROM lmc_calendar_summaries')
        for record in records:
            c.execute('INSERT INTO lmc_calendar_summaries VALUES (?,?,?,?,?,?,?,?,?)',record[:9])
            c.executemany('INSERT INTO lmc_calendar_sources VALUES (?,?,?)',
                          [(record[0],m['memory_id'],m['revision']) for m in record[9]])
        c.execute("INSERT INTO memory_config VALUES ('calendar_summary_signature',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(signature,))
    return len(records)


def _calendar_summary(c, item, level):
    occurred=str(item.get('occurred_at') or '')
    if not occurred:return None
    try:start,_=_period(datetime.fromisoformat(occurred.replace('Z','+00:00')),level)
    except ValueError:return None
    row=c.execute('''SELECT s.* FROM lmc_calendar_summaries s
        JOIN lmc_calendar_sources x USING(summary_id)
        JOIN lmc_memories m ON m.memory_id=x.memory_id AND m.revision=x.source_revision
        WHERE x.memory_id=? AND s.period_type=? AND s.period_start=? AND s.primary_scope=?''',
        (item['memory_id'],level,start,item.get('primary_scope'))).fetchone()
    return dict(row) if row else None


def apply_resolution(store, packet, query, now=None):
    """Project authoritative hits to full/summary/pointer without mutating memory."""
    now_dt=datetime.fromisoformat(utc(now));explicit=packet.get('query_intent')=='explicit_memory_request'
    with store.connect() as c:
        for item in packet.get('memories',[]):
            if item.get('memory_kind')=='raw_experience':
                item['retrieval_resolution']='pointer'
                continue
            row=c.execute('SELECT title FROM lmc_memories WHERE memory_id=?', (item.get('memory_id'),)).fetchone()
            if row:
                item.setdefault('title', row['title'])
                item['retrieval_resolution'] = 'full'
    # Projection can make two different hits identical; dedup once more.
    seen=set();selected=[]
    for item in packet.get('memories',[]):
        fingerprint=content_fingerprint(item.get('content',''))
        if fingerprint in seen:
            packet['omitted']['duplicate_count']+=1;continue
        seen.add(fingerprint);selected.append(item)
    packet['memories']=selected
    return packet
