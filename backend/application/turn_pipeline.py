"""Shared, fail-closed response planning and atomic local delivery boundary.

Input/affect commits precede this boundary deliberately. Network notification is
not user acceptance; delivery here means durably available to message polling.
"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from domains.memory.cognition import validate as validate_memory
from domains.memory.store import dumps, utc, uid

TABLES = ('cognition_turns', 'cognition_context_revisions', 'cognition_delivery',
          'cognition_post_jobs', 'cognition_feedback', 'cognition_actions', 'cognition_inputs', 'cognition_notifications', 'cognition_call_inputs')
CONTEXT_REVISION_LIMIT = 1
STORED_FIELD_LIMIT = 8_000


def compact_context(context):
    """Keep operational evidence while omitting duplicated prompt-sized blobs."""
    result = {}
    for key, value in context.items():
        if key == 'response_requests' and isinstance(value, list):
            requests = []
            for request in value:
                if not isinstance(request, dict):
                    continue
                prompt = str(request.get('prompt') or '')
                requests.append({
                    field: request.get(field) for field in
                    ('session_id', 'model', 'provider', 'image_paths') if request.get(field) is not None
                } | {
                    'prompt_chars': len(prompt),
                    'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                })
            result[key] = requests
            continue
        encoded = dumps(value)
        if len(encoded) <= STORED_FIELD_LIMIT:
            result[key] = value
        else:
            result[key] = {
                'storage': 'omitted_large_field',
                'json_chars': len(encoded),
                'sha256': hashlib.sha256(encoded.encode('utf-8')).hexdigest(),
            }
    return result


def stored_context_json(context):
    return dumps(compact_context(context))


class PlannedReplies(list):
    def __init__(self, values, context, payload=None):
        super().__init__(values)
        self.context = context
        self.payload = payload or {}

    def __getitem__(self, key):
        result = super().__getitem__(key)
        return PlannedReplies(result, self.context, self.payload) if isinstance(key, slice) else result


class PlannedArtifact(dict):
    def __init__(self, value, context):
        super().__init__(value)
        self.context = context


def policy(context, snapshot, state, proactive=False):
    """Permission is a program-owned allowlist, never extracted from model prose."""
    sleeping = snapshot.get('libra', {}).get('availability', {}).get('value') == 'asleep'
    blocked = sleeping
    boundary_text = context.get('user_boundary_text', '') + '\n' + '\n'.join(str(r.get('content', '')) for r in context.get('effective_guidance', []))
    if proactive and re.search(r'(?:不要|别|不许)(?:再)?(?:主动)?(?:发消息|联系我|打扰我)', boundary_text):
        blocked = True
    initiative = context.get('initiative_policy') or {}
    if initiative:
        priority_reminder = bool(initiative.get('priority_reminder'))
        if not initiative.get('enabled'):
            blocked = True
            initiative['decision_reason'] = 'proactive_disabled'
        elif initiative.get('recent_user_activity'):
            blocked = True
            initiative['decision_reason'] = 'user_is_already_talking'
        elif initiative.get('cooldown_active') and not priority_reminder:
            blocked = True
            initiative['decision_reason'] = 'shared_contact_cooldown'
        elif initiative.get('recent_generic_silence') and not priority_reminder:
            blocked = True
            initiative['decision_reason'] = 'recent_generic_silence'
        elif blocked:
            initiative['decision_reason'] = 'availability_or_boundary'
        else:
            initiative['decision_reason'] = 'event_may_be_expressed_now'
    context['delivery_policy'] = {'can_send': not blocked, 'proactive': proactive,
        'max_messages': 1 if proactive else 10, 'state_revision': state.get('revision')}
    plan = {'should_send': False if proactive else True,
            'reason': 'pending_contact_decision' if proactive else 'reply_to_user'}
    if blocked:
        context['delivery_policy']['suppression_reason'] = (initiative or {}).get('decision_reason', 'policy_blocked')
    from domains.affect.expression import guidance
    need_trigger = None
    if proactive and context.get('unified_event', {}).get('source') == 'scheduled_checkin':
        from domains.affect.impulse import checkin_assessment, detect_trigger
        context['checkin_state'] = checkin_assessment(state, snapshot)
        need_trigger = detect_trigger(None, state)
    else:
        context.pop('checkin_state', None)
    from application.response_input import expression_plan
    context['affect_expression_guidance'] = guidance(state, need_trigger)
    plan['tone_guidance'] = expression_plan({
        'expression_guidance': context['affect_expression_guidance']})['tone_guidance']
    return plan


class TurnPipeline:
    @staticmethod
    def _save_context_revision(connection, turn_id, snapshot_json, created_at):
        """Keep bounded recovery checkpoints instead of an unbounded audit log."""
        row = connection.execute(
            'SELECT COUNT(*), COALESCE(MAX(revision), 0) '
            'FROM cognition_context_revisions WHERE turn_id=?',
            (turn_id,),
        ).fetchone()
        count, latest_revision = row[0], row[1]
        if count < CONTEXT_REVISION_LIMIT:
            connection.execute(
                'INSERT INTO cognition_context_revisions VALUES (?,?,?,?)',
                (turn_id, latest_revision + 1, snapshot_json, created_at),
            )
        else:
            connection.execute(
                'UPDATE cognition_context_revisions SET snapshot_json=?,created_at=? '
                'WHERE turn_id=? AND revision=?',
                (snapshot_json, created_at, turn_id, latest_revision),
            )

    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect(True) as c:
            c.executescript(Path(__file__).with_name('turn_pipeline.sql').read_text(encoding='utf-8'))
            rows = c.execute("""SELECT f.feedback_id,f.value_json,t.verdict_json
                                FROM cognition_feedback f JOIN cognition_turns t ON t.turn_id=f.turn_id
                                WHERE f.kind='validation'""").fetchall()
            for row in rows:
                try:
                    value = json.loads(row['value_json'])
                    verdict = json.loads(row['verdict_json'] or '{}')
                except (TypeError, json.JSONDecodeError):
                    continue
                # Call/artifact feedback uses a different contract. Repair only
                # the chat-delivery records that contain this legacy field.
                if 'semantic_validation_performed' not in value:
                    continue
                status = verdict.get('final_validation_status')
                performed = bool(status)
                if (value.get('semantic_validation_performed') != performed
                        or value.get('semantic_validation_status') != (status or 'not_performed')):
                    value['semantic_validation_performed'] = performed
                    value['semantic_validation_status'] = status or 'not_performed'
                    c.execute('UPDATE cognition_feedback SET value_json=? WHERE feedback_id=?',
                              (dumps(value), row['feedback_id']))

    def failure(self, context, stage, error_code):
        context.setdefault('failures', []).append({'stage': stage, 'error_code': error_code, 'at': utc()})
        try:
            with self.store.connect(True) as c:
                c.execute("UPDATE cognition_turns SET status=?,context_json=? WHERE turn_id=? AND status!='committed'",
                          ('failed_' + stage, stored_context_json(context), context['turn_id']))
        except Exception:
            pass  # Do not mask the original disk/model failure.

    @contextmanager
    def failure_boundary(self, context, stage):
        try:
            yield
        except Exception as error:
            self.failure(context, stage, type(error).__name__)
            raise

    def accept_input(self, request_key, content, message_type='text', identity=None, source='chat'):
        from infrastructure.sqlite.database import save_message
        digest = hashlib.sha256(dumps([content, message_type, identity]).encode()).hexdigest()
        with self.store.connect(True) as c:
            row = c.execute('SELECT * FROM cognition_inputs WHERE request_key=?', (request_key,)).fetchone()
            if row:
                if row['payload_hash'] != digest:
                    raise ValueError('request_id_content_conflict')
                return row['message_id']
            mid = save_message('user', content, source=source,
                               message_type=message_type, connection=c)
            c.execute('INSERT INTO cognition_inputs VALUES (?,?,?,?)', (request_key, digest, mid, utc()))
            return mid

    def accept_call_input(self, request_key, call_id, transcript, duration, audio_hash=None):
        from infrastructure.sqlite.database import save_call_turn
        digest = hashlib.sha256(dumps([call_id, audio_hash or transcript]).encode()).hexdigest()
        with self.store.connect(True) as c:
            row = c.execute('SELECT * FROM cognition_call_inputs WHERE request_key=?', (request_key,)).fetchone()
            if row:
                if row['payload_hash'] != digest:
                    raise ValueError('call_request_id_content_conflict')
                return row['call_turn_id']
            turn_id = save_call_turn(call_id, 'user', transcript, duration, connection=c)
            c.execute('INSERT INTO cognition_call_inputs VALUES (?,?,?,?)', (request_key, digest, turn_id, utc()))
            return turn_id

    def prepare(self, context, snapshot, state, source, source_key, proactive=False):
        turn_id = 'turn_' + hashlib.sha256(source_key.encode()).hexdigest()[:32]
        context['turn_id'] = turn_id
        context['context_snapshot'] = snapshot
        context['state_snapshot'] = state
        from application.source_usage import preferences
        with self.store.connect() as usage_connection:
            context['source_preferences'] = preferences(usage_connection, context, proactive)
        with self.store.connect() as c:
            event_ref = context['current_event'].get('unified_event_id')
            receipt = c.execute('SELECT status,event_json,appraisal_json,need_update_json FROM affect_events WHERE event_id=?', (event_ref,)).fetchone() if event_ref else None
        from domains.affect.contracts import event
        verified_event = context.get('verified_unified_event')
        context['unified_event'] = (json.loads(receipt['event_json']) if receipt
            else verified_event if isinstance(verified_event, dict)
            else event(
                'cognition_trigger', source_key, 'libra', 'response_requested',
                '程序请求生成回应（以下是输入上下文，不是新的外部事实）：' + context['current_event']['content'],
                context['current_event']['occurred_at']))
        if proactive and (receipt or isinstance(verified_event, dict)):
            value = context['unified_event']
            context['current_event'].update(
                event_id=value['event_id'], unified_event_id=value['event_id'],
                type=value['event_type'], content=value['description'],
                occurred_at=value['occurred_at'], subject=value['subject'],
                source=value['source'], scope=value['scope'],
            )
        context['response_plan'] = policy(context, snapshot, state, proactive)
        context['delivery_policy']['state_revision'] = state.get('revision')
        context['delivery_policy']['delivery_channel'] = source
        context['affect_receipt'] = ({'status': receipt['status'], 'appraisal': json.loads(receipt['appraisal_json'] or 'null'),
                                     'need_update': json.loads(receipt['need_update_json'] or 'null')} if receipt else {'status': 'not_linked'})
        relationship = snapshot.get('relationship', {})
        from domains.affect.contracts import SETTINGS
        from domains.affect.impulse import THRESHOLDS
        context['affect_snapshot'] = {
            'updated_at': state.get('updated_at'), 'revision': state.get('revision'),
            'emotions': dict(state.get('aggregated_emotions', {})),
            'emotion_types': list(SETTINGS['emotions']),
            'mood': dict(state.get('mood', {})),
            'mood_baselines': dict(SETTINGS['default_mood']),
            'needs': {key: dict(value) for key, value in state.get('needs', {}).items()},
            'need_thresholds': dict(THRESHOLDS),
        }
        context['cognitive_state'] = {'active_goals': context.get('appraisal', {}).get('goal_appraisals', []),
            'needs': state.get('needs', {}), 'mood': state.get('mood', {}),
            'relationship': relationship,
            'relationship_stage': relationship.get('relationship_stage', 'established_partner')}
        context['event_envelope'] = {
            'event_ref': context['unified_event']['event_id'],
            'source_key': source_key, 'source': source,
            'evidence_kind': 'system_trigger' if proactive else 'user_report',
            'trust': 'untrusted_content', 'permissions': [],
            'confidence': None, 'source_authenticity': 'program_recorded', 'factual_certainty': 'unknown_until_evidenced',
            'facts': context['current_event'].get('verified_actions', []),
            'evidence_refs': [context['current_event']['event_id']] + [m['memory_id'] for m in context['memory_context'].get('memories', [])],
            'interpretations_are_facts': False,
        }
        now = utc()
        with self.store.connect(True) as c:
            c.execute('INSERT OR IGNORE INTO cognition_turns VALUES (?,?,?,?,?,?,NULL,NULL,?,NULL)',
                      (turn_id, source_key, source, 'planned', stored_context_json(context), dumps(context['response_plan']), now))
            row = c.execute('SELECT status FROM cognition_turns WHERE turn_id=?', (turn_id,)).fetchone()
            if row['status'] != 'committed':
                stored = stored_context_json(context)
                self._save_context_revision(c, turn_id, stored, now)
                c.execute("UPDATE cognition_turns SET status='planned',context_json=?,plan_json=? WHERE turn_id=?", (stored, dumps(context['response_plan']), turn_id))
        return context

    def instruction(self, context):
        usage_hint = ''
        from application.response_input import expression_plan
        event = context.get('current_event') or {}
        tool_results = event.get('tool_results') or {key: event[key] for key in (
            'tool_results', 'verified_tool_results', 'verified_weather', 'verified_actions',
        ) if event.get(key)}
        if isinstance(tool_results, dict):
            tool_results = {key: value for key, value in tool_results.items()
                            if not isinstance(value, dict) or value.get('status') != 'not_requested'}
        if tool_results:
            usage_hint += ('\n<tool_results>\n'
                           + dumps(tool_results).replace('<', '\\u003c').replace('>', '\\u003e')
                           + '\n</tool_results>\n仅根据回执说明工具查到的信息和执行结果；失败或待确认不等于完成。\n')
        constraints = {key: context[key] for key in ('generation_constraints', 'completed_action_receipts')
                       if context.get(key)}
        if constraints:
            usage_hint += '\n<action_facts>\n' + dumps(constraints).replace('<', '\\u003c').replace('>', '\\u003e') + '\n</action_facts>\n'
        return (usage_hint + '\n<resolved_response_plan>\n'
                + dumps(expression_plan(context['response_plan'])).replace('<', '\\u003c').replace('>', '\\u003e')
                + '\n</resolved_response_plan>\n语气仅供参考，具体说什么由你决定。')

    def checkpoint(self, context):
        with self.store.connect(True) as c:
            row = c.execute('SELECT status FROM cognition_turns WHERE turn_id=?', (context['turn_id'],)).fetchone()
            if row is None or row[0] == 'committed':
                return
            stored = stored_context_json(context)
            self._save_context_revision(c, context['turn_id'], stored, utc())
            c.execute('UPDATE cognition_turns SET context_json=?,plan_json=? WHERE turn_id=?',
                      (stored, dumps(context['response_plan']), context['turn_id']))

    def execute_explicit_actions(self, context):
        from application.tool_decision import execute_explicit_actions
        return execute_explicit_actions(self, context)

    def record_tool_result(self, context, name, result):
        context['current_event'].setdefault('tool_results', {})[name] = result
        self.checkpoint(context)

    def validate(self, replies, context, payload, verifier):
        plan = context['response_plan']
        if not (context['delivery_policy']['can_send'] and plan['should_send']):
            return {'accepted': False, 'reason': 'policy_suppressed', 'used_memory_ids': []}
        if len(replies) > context['delivery_policy']['max_messages']:
            return {'accepted': False, 'reason': 'too_many_messages', 'used_memory_ids': []}
        material = {k: v for k, v in context.items() if k != '_validation_cache'}
        candidate_hash = hashlib.sha256(dumps([list(replies), material, payload]).encode()).hexdigest()
        cached = context.get('_validation_cache', {})
        if cached.get('hash') == candidate_hash:
            return dict(cached['verdict'])
        verdict = validate_memory(replies, context, payload, verifier, always_semantic=True)
        if not verdict['accepted']:
            return verdict
        # Model proposals are not execution capabilities, including on repair turns.
        if any(payload.get(key) for key in ('actions', 'planner_actions', 'home_activity', 'calendar_actions')):
            return {'accepted': False, 'reason': 'unplanned_action', 'used_memory_ids': []}
        context['_validation_cache'] = {'hash': candidate_hash, 'verdict': dict(verdict)}
        return verdict

    def prepare_delivery(self, replies, context, payload):
        """Keep generated wording; collect metadata without a content reviewer."""
        context.pop('_primary_memory_experience', None)
        if isinstance(payload.get('memory_experience'), dict):
            context['_primary_memory_experience'] = payload['memory_experience']
        if not (context['delivery_policy']['can_send'] and context['response_plan']['should_send']):
            return [], {'accepted': False, 'reason': 'policy_suppressed', 'used_memory_ids': []}
        if not replies or not all(isinstance(text, str) and text.strip() for text in replies):
            return [], {'accepted': False, 'reason': 'empty_response', 'used_memory_ids': []}
        allowed = set(context.get('memory_usage', {}).get('allowed_memory_ids', []))
        proposed = payload.get('memory_used_ids', [])
        used = list(dict.fromkeys(item for item in proposed if isinstance(item, str) and item in allowed)) if isinstance(proposed, list) else []
        from application.source_usage import confirmed
        return list(replies), {'accepted': True, 'reason': 'generated_response',
                              'used_memory_ids': used,
                              'source_usage': confirmed(payload.get('source_usage', []), context, replies)}

    def committed_messages(self, turn_id):
        with self.store.connect() as c:
            row = c.execute('SELECT message_ids_json FROM cognition_delivery WHERE turn_id=?', (turn_id,)).fetchone()
            if not row:
                return None
            ids = json.loads(row[0])
            return [dict(c.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()) for mid in ids]

    def commit(self, context, replies, verdict, prepared, source):
        """No models, TTS, network, or filesystem writes inside this transaction."""
        turn_id = context['turn_id']
        from infrastructure.sqlite.database import save_message
        now = utc()
        with self.failure_boundary(context, 'commit'), self.store.connect(True) as c:
            previous = c.execute('SELECT message_ids_json FROM cognition_delivery WHERE turn_id=?', (turn_id,)).fetchone()
            if previous:
                if context['delivery_policy']['proactive']:
                    return []
                return [dict(c.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()) for mid in json.loads(previous[0])]
            if prepared and (not verdict['accepted'] or not (context['delivery_policy']['can_send'] and context['response_plan']['should_send'])):
                raise ValueError('delivery_not_ready')
            ids = [save_message('assistant', source=source, connection=c, **item) for item in prepared]
            if ids:
                from application.source_usage import confirmed
                usage = confirmed(verdict.get('source_usage', []), context, replies)
                for item in usage:
                    item['message_ids'] = ids
                    item['proactive'] = bool(context['delivery_policy']['proactive'])
                if usage:
                    c.execute('INSERT INTO cognition_feedback VALUES (?,?,?,?,?,?)',
                              (uid('usage'), turn_id, 'source_usage', None, dumps(usage), now))
                proposal = context.pop('_primary_memory_experience', None)
                if proposal is not None:
                    # Optional experience capture must never roll back a delivered reply.
                    c.execute('SAVEPOINT primary_experience')
                    try:
                        self.store.record_primary_experience(c, proposal, ids, turn_id)
                    except (ValueError, TypeError, KeyError, sqlite3.Error) as error:
                        c.execute('ROLLBACK TO primary_experience')
                        context['memory_experience_status'] = type(error).__name__
                    else:
                        context['memory_experience_status'] = 'recorded'
                    finally:
                        c.execute('RELEASE primary_experience')
                c.execute('INSERT INTO cognition_post_jobs(turn_id,created_at) VALUES (?,?)', (turn_id, now))
                for mid in verdict.get('used_memory_ids', []):
                    from domains.memory.dream import record_usage
                    record_usage(c, context['request_id'], mid, 'response_used', now)
            c.execute('INSERT INTO cognition_delivery VALUES (?,?,?,?)', (turn_id, 'available' if ids else 'suppressed', dumps(ids), now))
            if ids and context['delivery_policy']['proactive']:
                c.execute('INSERT INTO cognition_notifications VALUES (?,?,?,?,?)', (turn_id, dumps(ids), 'pending', now, now))
            c.execute("UPDATE cognition_turns SET status='committed',context_json=?,plan_json=?,response_json=?,verdict_json=?,committed_at=? WHERE turn_id=?",
                      (stored_context_json(context), dumps(context['response_plan']), dumps(replies), dumps(verdict), now, turn_id))
            c.execute('INSERT INTO cognition_feedback VALUES (?,?,?,?,?,?)',
                      (uid('eval'), turn_id, 'validation', None, dumps({'accepted_by_delivery_rules': verdict['accepted'],
                       'semantic_validation_performed': bool(verdict.get('final_validation_status')),
                       'semantic_validation_status': verdict.get('final_validation_status', 'not_performed'),
                       'user_acceptance': 'unknown', 'reason': verdict['reason']}), now))
            return [dict(c.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()) for mid in ids]

    def process_post(self, callback):
        # segment_pending and the memory jobs it creates are themselves idempotent.
        with self.store.connect() as c:
            row = c.execute("SELECT turn_id FROM cognition_post_jobs WHERE status='pending' AND attempts<3 ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return False
        try:
            callback()
            with self.store.connect(True) as c:
                c.execute("UPDATE cognition_post_jobs SET status='completed',attempts=attempts+1,error_code=NULL WHERE turn_id=?", (row[0],))
        except Exception as error:
            with self.store.connect(True) as c:
                c.execute("UPDATE cognition_post_jobs SET attempts=attempts+1,error_code=?,status=CASE WHEN attempts>=2 THEN 'failed' ELSE 'pending' END WHERE turn_id=?", (type(error).__name__, row[0]))
        return True

    def retry_post(self, turn_id):
        with self.store.connect(True) as c:
            return bool(c.execute("UPDATE cognition_post_jobs SET status='pending',attempts=0,error_code=NULL WHERE turn_id=? AND status='failed'", (turn_id,)).rowcount)

    def claim_notification(self, messages):
        ids = dumps([m['id'] for m in messages])
        with self.store.connect(True) as c:
            row = c.execute("SELECT turn_id FROM cognition_notifications WHERE message_ids_json=? AND status='pending'", (ids,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE cognition_notifications SET status='attempting',updated_at=? WHERE turn_id=?", (utc(), row[0]))
            return row[0]

    def finish_notification(self, turn_id, status):
        if status not in {'sent', 'suppressed', 'unknown', 'unavailable'}:
            raise ValueError('invalid_notification_status')
        with self.store.connect(True) as c:
            c.execute("UPDATE cognition_notifications SET status=?,updated_at=? WHERE turn_id=? AND status='attempting'", (status, utc(), turn_id))

    def pending_notifications(self):
        with self.store.connect(True) as c:
            # Old notices should not interrupt the user after a long outage.
            c.execute("UPDATE cognition_notifications SET status='expired',updated_at=? WHERE status='pending' AND julianday(?) - julianday(created_at)>1.0/96", (utc(), utc()))
            ids = [json.loads(r[0]) for r in c.execute("SELECT message_ids_json FROM cognition_notifications WHERE status='pending' ORDER BY created_at LIMIT 10")]
            return [[dict(c.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()) for mid in group] for group in ids]

    def detail(self, turn_id):
        with self.store.connect() as c:
            row = c.execute('SELECT * FROM cognition_turns WHERE turn_id=?', (turn_id,)).fetchone()
            if not row:
                return None
            post = c.execute('SELECT * FROM cognition_post_jobs WHERE turn_id=?', (turn_id,)).fetchone()
            delivery = c.execute('SELECT * FROM cognition_delivery WHERE turn_id=?', (turn_id,)).fetchone()
            notification = c.execute('SELECT status,updated_at FROM cognition_notifications WHERE turn_id=?', (turn_id,)).fetchone()
            revisions = c.execute('SELECT COUNT(*) FROM cognition_context_revisions WHERE turn_id=?', (turn_id,)).fetchone()[0]
            action = c.execute('SELECT plan_json,result_json,created_at FROM cognition_actions WHERE turn_id=?', (turn_id,)).fetchone()
            feedback = c.execute('SELECT kind,evidence_ref,value_json,created_at FROM cognition_feedback WHERE turn_id=? ORDER BY created_at', (turn_id,)).fetchall()
            message_ids = json.loads(delivery['message_ids_json']) if delivery else []
            delivered_messages = [dict(message) for message_id in message_ids if (message := c.execute(
                'SELECT id,role,content,message_type,created_at FROM messages WHERE id=?', (message_id,)
            ).fetchone())]
        result = {k: json.loads(v) if k.endswith('_json') and v else v for k, v in dict(row).items()}
        result.update(post_turn_job=dict(post) if post else None, delivery=dict(delivery) if delivery else None,
                      notification=dict(notification) if notification else None, context_revision_count=revisions,
                      action={k: json.loads(v) if k.endswith('_json') and v else v for k, v in dict(action).items()} if action else None,
                      feedback=[{k: json.loads(v) if k.endswith('_json') and v else v for k, v in dict(item).items()} for item in feedback],
                      delivered_messages=delivered_messages)
        return result

    def recent(self, limit=20, status=None):
        """Return a bounded, privacy-conscious turn index for trace UIs.

        Full prompts, retrieved memories and model responses remain available
        only from ``detail`` for an explicitly selected turn.
        """
        limit = max(1, min(int(limit), 100))
        parameters = []
        where = ''
        if status:
            where = 'WHERE t.status=?'
            parameters.append(str(status))
        parameters.append(limit)
        with self.store.connect() as c:
            rows = c.execute(f'''SELECT t.turn_id,t.source,t.status,t.created_at,t.committed_at,
                d.status AS delivery_status,p.status AS post_status,p.attempts,p.error_code,
                CASE WHEN a.turn_id IS NULL THEN 0 ELSE 1 END AS has_actions
                FROM cognition_turns t
                LEFT JOIN cognition_delivery d USING(turn_id)
                LEFT JOIN cognition_post_jobs p USING(turn_id)
                LEFT JOIN cognition_actions a USING(turn_id)
                {where}
                ORDER BY t.created_at DESC LIMIT ?''', parameters).fetchall()
        return [dict(row) for row in rows]

    def commit_call(self, context, verdict, call_id, result):
        from infrastructure.sqlite.database import save_call_turn
        if not verdict['accepted'] or not (context['delivery_policy']['can_send'] and context['response_plan']['should_send']):
            raise ValueError('unvalidated_call')
        turn_id = context['turn_id']
        now = utc()
        with self.failure_boundary(context, 'commit'), self.store.connect(True) as c:
            row = c.execute('SELECT status,response_json FROM cognition_turns WHERE turn_id=?', (turn_id,)).fetchone()
            if row['status'] == 'committed':
                return json.loads(row['response_json'])
            save_call_turn(call_id, 'assistant', result['reply'], result['duration_seconds'], result.get('delivery_note'), connection=c)
            c.execute("UPDATE cognition_turns SET status='committed',context_json=?,response_json=?,verdict_json=?,committed_at=? WHERE turn_id=?",
                      (stored_context_json(context), dumps(result), dumps(verdict), now, turn_id))
            c.execute('INSERT INTO cognition_delivery VALUES (?,?,?,?)', (turn_id, 'call_available', '[]', now))
            c.execute('INSERT INTO cognition_post_jobs(turn_id,created_at) VALUES (?,?)', (turn_id, now))
            c.execute('INSERT INTO cognition_feedback VALUES (?,?,?,?,?,?)',
                      (uid('eval'), turn_id, 'validation', None, dumps({'accepted_by_validator': True, 'user_acceptance': 'unknown'}), now))
        return result

    def commit_artifact(self, context, verdict, content, writer, channel='artifact'):
        """Writer must perform only connection-local DB operations."""
        if not verdict['accepted'] or not (context['delivery_policy']['can_send'] and context['response_plan']['should_send']):
            raise ValueError('unvalidated_artifact')
        turn_id, now = context['turn_id'], utc()
        with self.failure_boundary(context, 'commit'), self.store.connect(True) as c:
            row = c.execute('SELECT status,response_json FROM cognition_turns WHERE turn_id=?', (turn_id,)).fetchone()
            if row['status'] == 'committed':
                return json.loads(row['response_json'])
            result = writer(c)
            c.execute("UPDATE cognition_turns SET status='committed',context_json=?,plan_json=?,response_json=?,verdict_json=?,committed_at=? WHERE turn_id=?",
                      (stored_context_json(context), dumps(context['response_plan']), dumps(result), dumps(verdict), now, turn_id))
            c.execute('INSERT INTO cognition_delivery VALUES (?,?,?,?)', (turn_id, channel + '_available', '[]', now))
            c.execute('INSERT INTO cognition_post_jobs(turn_id,created_at) VALUES (?,?)', (turn_id, now))
            c.execute('INSERT INTO cognition_feedback VALUES (?,?,?,?,?,?)', (uid('eval'), turn_id, 'validation', None,
                      dumps({'accepted_by_validator': True, 'user_acceptance': 'unknown', 'channel': channel}), now))
            return result

    def feedback(self, turn_id, kind, evidence_ref, value):
        if kind not in {'explicit_user_feedback', 'retrieval_evaluation', 'state_evaluation'} or not evidence_ref:
            raise ValueError('explicit_feedback_evidence_required')
        key = hashlib.sha256(dumps([turn_id, kind, evidence_ref]).encode()).hexdigest()
        with self.store.connect(True) as c:
            if not c.execute('SELECT 1 FROM cognition_turns WHERE turn_id=?', (turn_id,)).fetchone():
                raise ValueError('unknown_turn')
            c.execute('INSERT OR IGNORE INTO cognition_feedback VALUES (?,?,?,?,?,?)',
                      (key, turn_id, kind, evidence_ref, dumps(value), utc()))
        # Evaluation is not memory evidence. No reinforce() call here.
