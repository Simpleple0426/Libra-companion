"""Explicit, journey-bound permission for an arrival message.

This is evidence/authority for Response Plan, not a proactive candidate queue.
"""
import json
import re
import threading
import time
from datetime import datetime

KEY = 'arrival_contact_authorization_v1'


class ArrivalAuthorization:
    def __init__(self, get_setting, set_setting, clock=time.time):
        self.get, self.set, self.clock = get_setting, set_setting, clock
        self.lock = threading.RLock()

    def _read(self):
        try:
            value = json.loads(self.get(KEY, '{}'))
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _write(self, state):
        self.set(KEY, json.dumps(state, ensure_ascii=False))

    def register(self, text, message_id, trip):
        text = text.strip().rstrip('。！!')
        with self.lock:
            state = self._read()
            if re.fullmatch(r'(?:你)?(?:到了)?(?:不用|不要|别)(?:再)?(?:告诉我|报备|报平安)(?:了)?', text):
                state.pop('request', None)
                state.pop('authorization', None)
                self._write(state)
                return 'cancelled'
            if not re.fullmatch(r'(?:你)?到了(?:告诉我|跟我说一声|和我说一声|报个平安)(?:一下|一声)?(?:吧|哦|呀)?', text):
                return None
            if not message_id or not trip or trip.get('state_type') != 'commuting' or not trip.get('end_location'):
                return 'unbound'
            try:
                end = datetime.fromisoformat(trip['end_time']).timestamp()
            except (ValueError, TypeError, KeyError):
                return 'unbound'
            if end <= self.clock():
                return 'unbound'
            request_id = str(message_id)
            if request_id in state.get('seen', []):
                return 'already_registered'
            state['seen'] = (state.get('seen', []) + [request_id])[-100:]
            state['request'] = dict(message_id=request_id, quote=text,
                trip_id=str(trip['id']), destination=trip['end_location'],
                expires=min(end + 600, self.clock() + 86400))
            self._write(state)
            return 'registered'

    def consume_for_arrival(self, previous, current, event_ref):
        with self.lock:
            state = self._read()
            request = state.get('request')
            if not request or request['expires'] <= self.clock():
                return None
            if (not previous or str(previous['id']) != request['trip_id']
                    or previous.get('state_type') != 'commuting'
                    or current.get('state_type') == 'commuting'
                    or current.get('from_location') != request['destination']):
                return None
            authorization = dict(reason='requested_arrival_report', event_ref=event_ref,
                evidence_refs=['messages:' + request['message_id']], request_quote=request['quote'],
                topic_key='arrival:' + request['trip_id'], arrival_state_id=str(current['id']),
                facts={'location': request['destination'], 'basis': 'libra_life_state'})
            state.pop('request', None)
            state['authorization'] = authorization
            self._write(state)
            return authorization

    def current(self):
        return self._read().get('authorization')

    def valid(self, authorization, current):
        return bool(current and authorization
                    and str(current['id']) == authorization.get('arrival_state_id')
                    and authorization == self._read().get('authorization'))
