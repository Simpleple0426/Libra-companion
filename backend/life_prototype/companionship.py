"""Durable user-led companionship; no inferred location or activity results."""
from copy import deepcopy
import json
import re

from .activity_engine import require
from .clock import utc
from .config import canonical, digest
from .store import Conflict


def _start_time_evidence(content, *, immediate):
    # Do not mistake an end time ("陪我到八点") for a start time.
    start_text = re.split(r'(?:直到|截至|结束时间|结束于|到(?:明天|今天|后天|晚上|下午|上午|中午|凌晨|\d|[一二三四五六七八九十两]))', content)[0]
    if immediate:
        return bool(re.search(r'现在(?:就)?(?:陪|开始|出发|走)|从现在|就现在|这就出发|马上出发', start_text))
    return bool(re.search(r'(?:\d{1,2}|[零一二三四五六七八九十两]{1,3})\s*(?:点|时|[:：]\d{2})|(?:半|\d+|[一二三四五六七八九十两]+)(?:个)?(?:小时|分钟)后', start_text))


def current(state, now):
    now = utc(now)
    return next((s for s in state.get('companionships', [])
                 if s['status'] != 'ended' and utc(s['start_at']) <= now
                 and (s['end_at'] is None or now < utc(s['end_at']))), None)


def item(session, now):
    from .coarse_plan import LOCAL, _at, schedule_day
    from datetime import timedelta
    # The day boundary is a display slice, never an implicit session end.
    start = max(utc(session['updated_at']), utc(_at(schedule_day(now), '04:00'))).isoformat()
    end = session['end_at'] or _at(schedule_day(now) + timedelta(days=1), '04:00').isoformat()
    return {'id': session['id'] + ':' + str(session['version']), 'appointment_id': session['id'],
            'kind': 'user_time', 'state_type': 'free', 'activity': 'user_time',
            'title': session['title'], 'intent': session['title'], 'place': None,
            'start_at': start, 'end_at': end,
            'start_time': utc(start).astimezone(LOCAL).strftime('%H:%M'),
            'end_time': utc(end).astimezone(LOCAL).strftime('%H:%M'),
            'source_message': session['source_message'], 'location_policy': 'unspecified',
            'companion_session_id': session['id'], 'open_ended': session['end_at'] is None,
            'status': 'in_progress', 'execution': 'reserved_user_time'}


def _write(cog, db, state, event_id, description, now, session):
    from .event_store import append
    state['revision'] += 1
    state['as_of'] = now.isoformat()
    receipt = {'event_id': event_id, 'revision': state['revision'],
               'occurred_at': now.isoformat(), 'recorded_at': now.isoformat()}
    # Keep the event's own title/status even if the session changes before ingestion.
    append(db, event_id, {'operation': 'companionship', 'description': description,
                         'companion': deepcopy(session)}, receipt, state, cog.p.config)
    db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1", (canonical(state),))


def reconcile(cog):
    """Activate/expire accepted sessions on the scheduler, including after restart."""
    now = cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = cog.store.read(db)
        for session in state.get('companionships', []):
            if session['status'] == 'ended':
                continue
            if session['end_at'] and utc(session['end_at']) <= now:
                session.update(status='ended', ended_at=session['end_at'], end_reason='explicit_end_time')
                state['companion_epoch'] = state.get('companion_epoch', 0) + 1
                _write(cog, db, state, session['id'] + ':expired',
                       '陪伴约定已结束，恢复自主生活安排', now, session)
            elif session['status'] == 'scheduled' and utc(session['start_at']) <= now:
                session.update(status='active', updated_at=now.isoformat())
                _write(cog, db, state, session['id'] + ':started', '左然正在' + session['title'], now, session)


def revise(cog, args):
    """Semantic proposals require current-message evidence and a state CAS."""
    from .cognition_contracts import shape
    shape({k: v for k, v in args.items() if k != 'context_message_id'}, {'message_id', 'expected_revision', 'action', 'session_id', 'title',
                 'start_at', 'end_at', 'outdoor', 'evidence_quote'})
    require(args['action'] in {'start', 'update', 'end', 'arrive_home'}, 'invalid companion action')
    require(type(args['expected_revision']) is int, 'state revision required')
    require(args['outdoor'] is None or type(args['outdoor']) is bool, 'invalid outdoor report')
    require(args['title'] is None or isinstance(args['title'], str) and 0 < len(args['title']) <= 160,
            'invalid companion title')
    now = cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT a.status,a.receipt,m.request FROM life_agenda_messages a '
                         'JOIN life_received_messages m ON m.id=a.message_id WHERE a.message_id=?',
                         (args['message_id'],)).fetchone()
        require(row is not None, 'unknown message')
        if row[0] in {'applied', 'none', 'clarify'}:
            receipt = json.loads(row[1])
            require(receipt.get('companion_proposal') == args, 'message already resolved differently')
            return receipt
        first = db.execute("SELECT message_id FROM life_agenda_messages WHERE status IN ('pending','running') ORDER BY rowid LIMIT 1").fetchone()
        require(first and first[0] == args['message_id'], 'resolve messages in order')
        message = json.loads(row[2])
        quote = args['evidence_quote']
        require(isinstance(quote, str) and quote.strip() and quote in message['content'], 'current message evidence required')
        state = cog.store.read(db)
        if state['revision'] != args['expected_revision']:
            raise Conflict('companion state changed; reread state')
        sessions = state.setdefault('companionships', [])
        session = next((s for s in sessions if s['id'] == args['session_id'] and s['status'] != 'ended'), None)
        if args['action'] == 'start':
            require(args['session_id'] is None, 'new session must not reference an old session')
            context = None
            if args.get('context_message_id'):
                prior = db.execute('SELECT id,request FROM life_received_messages WHERE rowid < '
                    '(SELECT rowid FROM life_received_messages WHERE id=?) ORDER BY rowid DESC LIMIT 8',
                    (args['message_id'],)).fetchall()
                context = next((json.loads(r[1]) for r in prior if r[0] == args['context_message_id']), None)
                require(context is not None and context.get('received_at') and
                        0 <= (utc(message.get('received_at') or now) - utc(context['received_at'])).total_seconds() <= 48 * 3600,
                        'companion context must reference a recent prior user message')
            invitation = quote if re.search(r'陪(?:我|着我|陪我|伴我|老婆)', quote) else (context or {}).get('content', '')
            require(re.search(r'(陪(?:我|着我|陪我)|陪伴我|陪老婆)', invitation), 'explicit invitation required')
            require(not re.search(r'(?:不用|不要|不需要|别).{0,4}陪|如果|假如|[“”「」『』"]', invitation),
                    'negated, hypothetical or quoted invitation requires clarification')
            immediate = args['start_at'] is None
            timing = _start_time_evidence(message['content'], immediate=immediate)
            if not timing and context:
                # "Now" in stale context cannot silently become "now" today.
                fresh = (utc(message.get('received_at') or now) - utc(context['received_at'])).total_seconds() <= 300
                timing = (not immediate or fresh) and _start_time_evidence(context['content'], immediate=immediate)
            if not timing:
                receipt = {'status': 'clarify', 'at': now.isoformat(), 'companion_proposal': args,
                           'reason': '陪伴开始时间尚未确定，请询问“什么时候开始/什么时候出发？”。结束时间可不指定，不要强制询问。',
                           'missing_fields': ['start_at'], 'schedule_changed': False}
                db.execute("UPDATE life_agenda_messages SET status='clarify',receipt=? WHERE message_id=?",
                           (canonical(receipt), args['message_id']))
                return receipt
            start = utc(args['start_at']) if args['start_at'] else utc(message.get('received_at') or now)
            require(args['start_at'] is None or start >= now, 'cannot schedule in the past')
            start = max(start, now)
            end = utc(args['end_at']) if args['end_at'] else None
            require(end is None or end > start, 'end must follow start')
            for old in sessions:
                if old['status'] == 'ended': continue
                require((old['end_at'] is not None and utc(old['end_at']) <= start)
                        or (end is not None and end <= utc(old['start_at'])),
                        'companionship overlaps; update existing session or clarify its end')
            from .appointments import display_title
            session = {'id': 'companion:' + digest(args['message_id'])[:24], 'version': 1,
                       'start_at': start.isoformat(), 'end_at': end.isoformat() if end else None,
                       'updated_at': start.isoformat(), 'status': 'active' if start <= now else 'scheduled',
                       'title': display_title(args['title']) if args['title'] else '陪伴用户',
                       'outdoor': args['outdoor'] is True, 'source_message': args['message_id']}
            sessions.append(session)
            description = '左然正在' + session['title'] if start <= now else '已约定' + session['title']
        else:
            require(session is not None, 'session ended or changed; reread state')
            require(session['end_at'] is None or utc(session['end_at']) > now, 'session has already expired')
            require(args['start_at'] is None, 'update cannot change start time')
            if args['action'] in {'end', 'arrive_home'}:
                # Deliberately conservative: ambiguous releases and quoted,
                # negated or hypothetical statements never pass this gate.
                sentence = re.sub(r'[\s，。！!,.～~]', '', message['content'])
                if args['action'] == 'end':
                    require(re.fullmatch(r'(?:你)?(?:不用|不需要|不要)(?:再|继续)?陪(?:着)?我(?:了|啦)?|(?:请)?结束陪伴(?:吧)?', sentence),
                            'requires unambiguous explicit end of companionship; manual end is available')
                else:
                    require(session['status'] == 'active' and session['outdoor'], 'home arrival only ends outdoor companionship')
                    require(re.fullmatch(r'(?:我|我们)?(?:已经)?(?:回到家|到家)(?:了|啦)', sentence),
                            'requires an unambiguous completed home-arrival report')
                session.update(status='ended', ended_at=now.isoformat(), end_reason=args['action'])
                state['companion_epoch'] = state.get('companion_epoch', 0) + 1
                description = '陪伴已结束，恢复自主生活安排'
            else:
                require(session['status'] == 'active', 'reports only update active companionship')
                if args['title'] is not None:
                    from .appointments import display_title
                    session['title'] = '陪伴用户' if args['title'] == '陪伴用户' else display_title(args['title'])
                if args['end_at'] is not None:
                    require(utc(args['end_at']) > now, 'new end must be in the future')
                    require(all(s['id'] == session['id'] or s['status'] == 'ended'
                                or (s['end_at'] and utc(s['end_at']) <= utc(session['start_at']))
                                or utc(args['end_at']) <= utc(s['start_at']) for s in sessions),
                            'new end overlaps another companion session')
                    session['end_at'] = utc(args['end_at']).isoformat()
                if args['outdoor'] is not None: session['outdoor'] = args['outdoor']
                session.update(updated_at=now.isoformat(), source_message=args['message_id'])
                description = '左然正在' + session['title']
            session['version'] += 1
        receipt = {'status': 'applied', 'companion_proposal': args, 'companion': deepcopy(session)}
        _write(cog, db, state, 'companion-message:' + args['message_id'], description, now, session)
        db.execute("UPDATE life_agenda_messages SET status='applied',receipt=? WHERE message_id=?",
                   (canonical(receipt), args['message_id']))
        return receipt


def manual_end(cog, session_id):
    now = cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = cog.store.read(db)
        session = next((s for s in state.get('companionships', []) if s['id'] == session_id), None)
        require(session is not None, 'unknown companion session')
        if session['status'] == 'ended': return {'status': 'ended', 'session_id': session_id}
        require(current(state, now) is session, 'stale button cannot end another or future session')
        session.update(status='ended', ended_at=now.isoformat(), end_reason='manual')
        session['version'] += 1
        state['companion_epoch'] = state.get('companion_epoch', 0) + 1
        event_id = session_id + ':manual-end'
        if db.execute("SELECT 1 FROM life_receipts WHERE category='event_control' AND id=?",
                      (event_id,)).fetchone():
            event_id += ':' + str(session['version'])
        _write(cog, db, state, event_id, '陪伴已结束，恢复自主生活安排', now, session)
    return {'status': 'ended', 'session_id': session_id}
