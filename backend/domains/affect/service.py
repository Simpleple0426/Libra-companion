"""Durable single-writer affect pipeline. Models never hold a SQLite transaction."""
import json
import os
import uuid
import time
from infrastructure.sqlite.connection import table_exists
from datetime import timedelta
from pathlib import Path

from .engine import initial, project, aggregate, appraise, elicit, update_needs
from domains.world.current_context import project as context_projection
from .contracts import iso, timestamp, SETTINGS, prompt


def memory_worthy_event(event):
    """Keep transient room navigation out of durable autobiographical memory."""
    if event.get('source') != 'user_life_activity':
        return True
    description = str(event.get('description') or '')
    generic_room = any(room in description for room in ('书房', '音乐室', '电影室'))
    navigation_only = '正在' in description or '离开了' in description
    has_grounded_activity = any(marker in description for marker in ('分钟', '小时', '结束学习：', '完成'))
    return not (generic_room and navigation_only and not has_grounded_activity)


class AffectService:
    def __init__(self,store):
        self.store=store
        self.context_provider=None

    def initialize(self):
        with self.store.connect(True) as c:
            c.executescript(Path(__file__).with_name('emotion_v1.sql').read_text(encoding='utf-8'))
            c.execute('DROP TABLE IF EXISTS affect_prospects')
            columns={row[1] for row in c.execute('PRAGMA table_info(affect_events)')}
            if 'error_detail' not in columns:c.execute('ALTER TABLE affect_events ADD COLUMN error_detail TEXT')
            if 'failed_output' not in columns:c.execute('ALTER TABLE affect_events ADD COLUMN failed_output TEXT')
            c.execute('INSERT OR IGNORE INTO affect_state VALUES (1,0,?)',(json.dumps(initial()),))

    def read(self,now=None):
        now=timestamp(now)
        with self.store.connect() as c:
            c.execute('BEGIN')
            row=c.execute('SELECT state_json,revision FROM affect_state WHERE id=1').fetchone()
            state=json.loads(row[0]);state['revision']=row['revision']
            interactions=[r[0] for r in c.execute("SELECT json_extract(event_json,'$.occurred_at') AS at FROM affect_events WHERE json_extract(event_json,'$.event_type')='user_message' AND json_extract(event_json,'$.occurred_at')>=? AND json_extract(event_json,'$.occurred_at')<=? ORDER BY at",(state['updated_at'],iso(now)))]
        for at in interactions:
            state=project(state,at)
            state['last_effective_interaction_at']=max(filter(None,[state.get('last_effective_interaction_at'),at]))
        return project(state,now)

    def enqueue(self,event,source_key,context):
        body=json.dumps(event,ensure_ascii=False)
        with self.store.connect(True) as c:
            old=c.execute('SELECT event_json FROM affect_events WHERE event_id=?',(event['event_id'],)).fetchone()
            if old and json.loads(old[0])!=event:raise ValueError('event_id_content_conflict')
            c.execute('INSERT OR IGNORE INTO affect_events(event_id,source_key,event_json,context_json,created_at) VALUES (?,?,?,?,?)',
                      (event['event_id'],source_key,body,json.dumps(context,ensure_ascii=False),iso()))
            c.execute('UPDATE affect_events SET context_json=? WHERE event_id=? AND context_json IS NULL',
                      (json.dumps(context,ensure_ascii=False),event['event_id']))
            routing = context.get('processing_route', {})
            if routing.get('appraisal') is False:
                c.execute("UPDATE affect_events SET status='committed',result_json=?,processed_at=? WHERE event_id=? AND status='pending' AND attempts=0",
                          (json.dumps({'processing_route': routing, 'appraisal_skipped': True}), iso(), event['event_id']))
        if (event['source'] not in {'conversation','scheduled_checkin','world_simulation'}
                and memory_worthy_event(event)):
            self.store.ingest(source_system='unified_event',source_id=event['event_id'],source_type='unified_event',
                              actor='user' if event['subject']=='user' else 'libra' if event['subject']=='libra' else 'system',
                              content=event['description'],occurred_at=event['occurred_at'])

    def process(self,model,event_id=None,now=None):
        now=timestamp(now);token=uuid.uuid4().hex
        started = time.monotonic()
        with self.store.connect(True) as c:
            c.execute("UPDATE affect_events SET status='failed',error_code='lease_attempts_exhausted',lease_token=NULL,lease_until=NULL WHERE status='processing' AND attempts>=3 AND lease_until<=?",(iso(now),))
            # One live writer across chat and proactive workers, including multiple processes.
            if c.execute("SELECT 1 FROM affect_events WHERE status='processing' AND lease_until>?",(iso(now),)).fetchone():return False
            row=c.execute("SELECT * FROM affect_events WHERE (status='pending' OR (status='processing' AND lease_until<=?)) AND attempts<3 AND (context_json IS NOT NULL OR json_extract(event_json,'$.event_type')!='user_message' OR datetime(created_at)<datetime(?,'-5 minutes')) AND (? IS NULL OR event_id=?) ORDER BY created_at LIMIT 1",(iso(now),iso(now),event_id,event_id)).fetchone()
            if not row:return False
            c.execute("UPDATE affect_events SET status='processing',lease_token=?,lease_until=?,attempts=attempts+1 WHERE event_id=?",(token,iso(now+timedelta(minutes=3)),row['event_id']))
            saved=c.execute('SELECT * FROM affect_state WHERE id=1').fetchone()
        event=json.loads(row['event_json'])
        # Legacy output receipts are no longer cognitive events. Drain pending
        # records without invoking models or changing affect state.
        if event['event_type'] == 'assistant_reply' or event['source'] in {'libra_internal_state', 'todo_reminder', 'content_discovery', 'world_simulation', 'tool_result', 'calendar'}:
            with self.store.connect(True) as c:
                c.execute("UPDATE affect_events SET status='committed',result_json=?,processed_at=?,lease_token=NULL,lease_until=NULL,error_code=NULL,error_detail=NULL,failed_output=NULL WHERE event_id=? AND lease_token=?",
                          (json.dumps({'skipped': 'retired_event_type'}), iso(now), row['event_id'], token))
            return True
        state=self.read(now)
        last_output=None
        def invoke(stage,text):
            nonlocal last_output
            # Renew between bounded model calls without holding a DB transaction
            # during inference. Longer agent paths retain the single-writer lease.
            logical_now = now + timedelta(seconds=time.monotonic() - started)
            with self.store.connect(True) as c:
                if not c.execute("UPDATE affect_events SET lease_until=? WHERE event_id=? AND lease_token=? AND status='processing' AND lease_until>?",
                                 (iso(logical_now + timedelta(minutes=3)), row['event_id'], token, iso(logical_now))).rowcount:
                    raise ValueError('affect_lease_lost')
            if row['error_detail']:
                text += ('\n<retry_feedback>\n上一次输出未通过程序校验：'
                         + str(row['error_detail'])[:500]
                         + '。请重新核对 required_output_contract，并只输出修正后的 JSON。\n</retry_feedback>')
            last_output=model(stage,text)
            return last_output
        try:
            from domains.world.current_context import build
            context=json.loads(row['context_json']) if row['context_json'] else self.context_provider() if self.context_provider else build(now)
            context['trigger_event_id']=event['event_id']
            with self.store.connect(True) as c:
                c.execute('UPDATE affect_events SET context_json=? WHERE event_id=? AND lease_token=?',(json.dumps(context),event['event_id'],token))
            if (event['source'] not in {'conversation','scheduled_checkin','world_simulation'}
                    and memory_worthy_event(event)):
                self.store.ingest(source_system='unified_event',source_id=event['event_id'],source_type='unified_event',
                    actor='user' if event['subject']=='user' else 'libra' if event['subject']=='libra' else 'system',
                    content=event['description'],occurred_at=event['occurred_at'])
            # Reuse frozen turn evidence; standalone events have no recalled memory.
            memories=context.get('relevant_memory', [])
            historical=(now-timestamp(event['occurred_at'])).total_seconds()>86400
            payload={'event':event,'current_context':context_projection(context,'appraisal'),
                     'relevant_memory':memories,'core_goals':SETTINGS['core_goals'],
                     'standards':SETTINGS['standards'],
                     'appraisal_mode':context.get('processing_route',{}).get('appraisal_mode','full')}
            agentic = bool(context.get('processing_route', {}).get('affect_agent')) and not historical and event['source'] != 'scheduled_checkin'
            if agentic:
                from .agent import run
                agent_trace = context['emotion_agent'] = {}
                try:
                    appraisal, changes = run({**payload, '_context': context}, state, invoke, now, agent_trace)
                except Exception as error:
                    agent_trace.update(stop_reason='failed', error=type(error).__name__)
                    if agent_trace.get('steps'):
                        agent_trace['steps'][-1]['status'] = 'failed'
                    raise
                finally:
                    with self.store.connect(True) as c:
                        c.execute('UPDATE affect_events SET context_json=? WHERE event_id=? AND lease_token=?',
                                  (json.dumps(context), event['event_id'], token))
            elif historical or event['source'] == 'scheduled_checkin':
                appraisal={'event_id':event['event_id'],'goal_appraisals':[],'standard_appraisals':[]}
            else:appraisal=appraise(payload,invoke('appraisal',prompt('appraisal',payload)))
            if any(g['prospect'] and timestamp(g['prospect']['valid_until'])<=now for g in appraisal['goal_appraisals']):raise ValueError('prospect_already_expired')
            instances=[] if agentic else elicit(appraisal,event['occurred_at'])
            state['instances'].extend(instances)
            state['aggregated_emotions']=aggregate(state['instances'],now)
            if agentic:
                pass  # Operations were selected by the emotion agent above.
            elif historical or event['source'] == 'scheduled_checkin':
                changes={'need_updates':[]}
            else:
                need_input={'event':event,'aggregated_emotions':state['aggregated_emotions'],'mood':state['mood'],
                            'current_context':context_projection(context,'need'),'need_state':{k:v['value'] for k,v in state['needs'].items()}}
                changes=update_needs(state,invoke('need_update',prompt('need_update',need_input)))
            if event['event_type']=='user_message':
                previous=state['last_effective_interaction_at']
                state['last_effective_interaction_at']=max(filter(None,[previous,event['occurred_at']]))
            self._commit(row,token,saved['revision'],state,appraisal,changes,now)
            return True
        except Exception as error:
            raw=getattr(error,'raw_output',None)
            if raw is None:raw=last_output
            if raw is not None and not isinstance(raw,str):
                try:raw=json.dumps(raw,ensure_ascii=False)
                except (TypeError,ValueError):raw=repr(raw)
            detail=(str(error).strip() or type(error).__name__)[:1000]
            with self.store.connect(True) as c:
                c.execute("UPDATE affect_events SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,error_code=?,error_detail=?,failed_output=?,lease_token=NULL,lease_until=NULL WHERE event_id=? AND lease_token=?",
                          (type(error).__name__,detail,(raw or '')[:8000],event['event_id'],token))
            return False

    def _commit(self,row,token,revision,state,appraisal,changes,now):
        with self.store.connect(True) as c:
            job=c.execute('SELECT * FROM affect_events WHERE event_id=?',(row['event_id'],)).fetchone()
            current=c.execute('SELECT revision FROM affect_state WHERE id=1').fetchone()[0]
            if job['lease_token']!=token or timestamp(job['lease_until'])<=now or current!=revision:raise ValueError('affect_revision_conflict')
            c.execute('UPDATE affect_state SET revision=revision+1,state_json=? WHERE id=1',(json.dumps(state),))
            c.execute("UPDATE affect_events SET status='committed',appraisal_json=?,need_update_json=?,result_json=?,processed_at=?,lease_token=NULL,lease_until=NULL,error_code=NULL,error_detail=NULL,failed_output=NULL WHERE event_id=?",
                      (json.dumps(appraisal),json.dumps(changes),json.dumps(state),iso(now),row['event_id']))

    def history(self,limit=50):
        with self.store.connect() as c:
            return [dict(r) for r in c.execute('SELECT event_id,status,attempts,error_code,created_at,processed_at FROM affect_events ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,200)),))]

    def detail(self,event_id):
        with self.store.connect() as c:row=c.execute('SELECT * FROM affect_events WHERE event_id=?',(event_id,)).fetchone()
        if not row:return None
        return {key.removesuffix('_json'):json.loads(value) if key.endswith('_json') and value else value for key,value in dict(row).items() if key not in {'lease_token'}}

    def retry(self,event_id):
        with self.store.connect(True) as c:
            return c.execute("UPDATE affect_events SET status='pending',attempts=0,lease_token=NULL,lease_until=NULL WHERE event_id=? AND status='failed'",(event_id,)).rowcount == 1


def presentation(state):
    labels={'joy':'开心','distress':'难受','happy_for':'替你高兴','sorry_for':'为你挂心','hope':'期待','fear':'担忧',
            'satisfaction':'满足','disappointment':'失望','relief':'安心','fears_confirmed':'担忧成真',
            'pride':'自豪','shame':'惭愧','admiration':'欣赏','reproach':'不认同','gratification':'欣慰','gratitude':'感激','remorse':'后悔','anger':'生气'}
    active=state.get('aggregated_emotions',{});kind=max(active,key=active.get) if active else None
    return {'schema_version':1,'dominant_emotion':labels.get(kind,'平静'),'active_intent':'','thought':'',
            'updated_at':state['updated_at'],'mood':state['mood'],'needs':state['needs'],
            'aggregated_emotions':active,'unavailable_legacy_fields':['intimacy','passion','commitment','longing','reflection','duty','rest','stress']}


def capture_user_message(connection,message_id,role,content,source,message_type, *, voice_emotion=None):
    """Transactional outbox: replies failing later cannot lose a user's affect event."""
    if role!='user' or source!='chat' or message_type not in {'text','voice','image','sticker','xhs_card'}:return
    if not table_exists(connection, 'affect_events'):return
    from .contracts import event
    at=connection.execute('SELECT created_at FROM messages WHERE id=?',(message_id,)).fetchone()[0]
    from .message_description import user_message_description
    description = user_message_description(content, message_type, voice_emotion=voice_emotion)
    value=event('conversation','messages:'+str(message_id),'user','user_message', description,at)
    from application.turn_routing import route_turn
    recent = [dict(r) for r in connection.execute('SELECT role,content FROM messages WHERE id<? ORDER BY id DESC LIMIT 6', (message_id,))][::-1]
    routing = route_turn(content, recent, has_attachment=message_type not in {'text', 'voice'})
    connection.execute('INSERT OR IGNORE INTO affect_events(event_id,source_key,event_json,created_at) VALUES (?,?,?,?)',
                      (value['event_id'],'messages:'+str(message_id),json.dumps(value,ensure_ascii=False),iso(at)))
    # Record the event atomically, but never queue unnecessary emotional work.
    # read() still projects time decay and records effective interaction time.
    if not routing['appraisal']:
        connection.execute("UPDATE affect_events SET status='committed',result_json=?,processed_at=? WHERE event_id=? AND status='pending' AND attempts=0",
                           (json.dumps({'processing_route': routing, 'appraisal_skipped': True}), iso(at), value['event_id']))


def capture_completion(connection,source,key,title,occurred_at):
    if source != 'habit_reminder':return
    if not table_exists(connection, 'affect_events'):return
    from .contracts import event
    value=event(source,key,'user','habit_completed','用户完成打卡：'+title,occurred_at)
    connection.execute('INSERT OR IGNORE INTO affect_events(event_id,source_key,event_json,created_at) VALUES (?,?,?,?)',
                      (value['event_id'],key,json.dumps(value,ensure_ascii=False),iso(occurred_at)))


def capture_life_activity(connection, row_id, description, occurred_at):
    if not table_exists(connection, 'affect_events'):return
    from .contracts import event
    from .activity_description import activity_description
    nickname = ''
    if table_exists(connection, 'app_settings'):
        row = connection.execute("SELECT value FROM app_settings WHERE key='user_nickname'").fetchone()
        nickname = (row[0] or '') if row else ''
    value=event('user_life_activity',str(row_id),'user','activity_updated',activity_description(description, nickname),occurred_at)
    connection.execute('INSERT OR IGNORE INTO affect_events(event_id,source_key,event_json,created_at) VALUES (?,?,?,?)',
                       (value['event_id'],str(row_id),json.dumps(value,ensure_ascii=False),iso()))






def capture_call_turn(connection,turn_id,role,content):
    if not table_exists(connection, 'affect_events'):return
    from .contracts import event
    turn=connection.execute('SELECT created_at,call_id FROM call_turns WHERE id=?',(turn_id,)).fetchone()
    at, call_id = turn[0], turn[1]
    key='call_turns:'+str(turn_id)
    if table_exists(connection, 'raw_experiences'):
        from domains.memory.store import uid, utc
        from infrastructure.sqlite.chat_session_state import current_session
        thread_id = current_session(connection)
        connection.execute('''INSERT INTO raw_experiences
            (experience_id,source_type,source_system,source_id,thread_id,actor,content,occurred_at,ingested_at,metadata_json)
            VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_system,source_id) DO NOTHING''',
            (uid('rx'),'chat_message','libra_call',str(turn_id),thread_id,
             'libra' if role=='assistant' else role,content,utc(at),utc(),json.dumps({'asr_uncertainty':role=='user','source_ref':key,'call_id':call_id})))
        from infrastructure.memory_wakeup import notify_after_commit
        notify_after_commit(connection, 'call')
    if role != 'user':return
    value=event('conversation',key,'user','user_message',
                '用户电话转写（可能有识别误差）：'+content,at)
    connection.execute('INSERT OR IGNORE INTO affect_events(event_id,source_key,event_json,created_at) VALUES (?,?,?,?)',
                       (value['event_id'],key,json.dumps(value,ensure_ascii=False),iso(at)))
