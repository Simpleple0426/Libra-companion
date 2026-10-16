"""Explicit, leased co-viewing sessions. Frames are transient movie evidence."""
import base64
import binascii
import io
import secrets
import threading
import time

from PIL import Image


class WatchService:
    INTERVALS = {"quiet": 300, "normal": 120, "chatty": 60}

    def __init__(self, generate, deliver, clock=time.monotonic, records=None, background=None):
        self.generate, self.deliver, self.clock = generate, deliver, clock
        self.lock = threading.RLock()
        self.session = None
        self.busy = False
        self.records = records
        self.background = background

    def current(self):
        with self.lock:
            if not self.session or self.session['expires'] < self.clock():
                return None
            return {k: self.session.get(k) for k in ('id', 'title', 'paused', 'position')}

    def finish(self, ident):
        with self.lock:
            if self.session and self.session['id'] == ident:
                self.session = None
            if self.records:
                self.records.control(ident, 'finish')

    def start(self, title, frequency):
        with self.lock:
            self.session = {"id": secrets.token_urlsafe(24), "title": title,
                "frequency": frequency, "paused": False, "revision": 0,
                "expires": self.clock() + 90, "last_attempt": float('-inf'),
                "summary": "", "last_sequence": -1}
            if self.records:
                self.records.start(self.session)
            if self.background:
                self.background.start(dict(self.session))
            return {"session_id": self.session['id'], "interval": self.INTERVALS[frequency]}

    def get(self, identity):
        if not self.session or not secrets.compare_digest(identity, self.session['id']):
            raise ValueError("陪看已结束，请重新开始")
        return self.session

    def control(self, identity, action):
        with self.lock:
            session = self.get(identity)
            if self.records:
                self.records.control(identity, action)
            if action == "stop":
                self.session = None
            elif action == 'resync':
                session.update(summary='', revision=session['revision'] + 1,
                               last_attempt=float('-inf'), expires=self.clock() + 90)
            elif action in {"pause", "resume"}:
                session.update(paused=action == "pause", revision=session['revision'] + 1,
                               expires=self.clock() + 90)
            else:
                # A timed-out lease cannot be silently revived mid-generation.
                if session['expires'] < self.clock():
                    session['revision'] += 1
                session['expires'] = self.clock() + 90
            return {"status": action, "revision": session['revision']}

    @staticmethod
    def decode(data):
        if not data.startswith("data:image/jpeg;base64,") or len(data) > 2_000_000:
            raise ValueError("画面必须为小于 1.5MB 的 JPEG")
        try:
            raw = base64.b64decode(data.split(',', 1)[1], validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != 'JPEG' or max(image.size) > 1920:
                    raise ValueError("画面尺寸过大")
                image.verify()
        except (OSError, binascii.Error, Image.DecompressionBombError) as error:
            raise ValueError("无法读取画面") from error
        return raw

    def observe(self, identity, sequence, frame, position=None, subtitles=None, timeline_revision=None):
        raw = self.decode(frame)
        subtitles = subtitles or []
        if subtitles and position is None:
            raise ValueError('字幕需要对应的播放时间')
        if sum(len(cue['text']) for cue in subtitles) > 18000:
            raise ValueError('单次字幕片段过长')
        if any(not (0 <= cue['start'] < cue['end'] <= position)
               or cue['end'] < max(0, position - 600) for cue in subtitles):
            raise ValueError('只能发送当前进度之前十分钟内已播放完的字幕')
        with self.lock:
            session = self.get(identity)
            if timeline_revision is not None and timeline_revision != session['revision']:
                return {"status": "cancelled", "messages": []}
            now = self.clock()
            if session['paused'] or session['expires'] < now:
                return {"status": "paused", "messages": []}
            if sequence <= session['last_sequence']:
                return {"status": "duplicate", "messages": []}
            session['last_sequence'] = sequence
            session['position'] = position
            if self.records:
                self.records.observed(session)
            background = self.background.get(identity) if self.background else {}
            if background.get('status') == 'loading':
                return {'status': 'preparing', 'messages': []}
            if self.busy or now - session['last_attempt'] < self.INTERVALS[session['frequency']]:
                return {"status": "watching", "messages": []}
            session['last_attempt'] = now
            revision = session['revision']
            snapshot = dict(session)
            if not session.get('background_injected'):
                snapshot['movie_background'] = background
            snapshot.update(position=position, subtitles=subtitles)
            self.busy = True
        try:
            result = self.generate(snapshot, raw)
            with self.lock:
                if (self.session is not session or session['paused']
                        or session['revision'] != revision or session['expires'] < self.clock()):
                    return {"status": "cancelled", "messages": []}
                if result is None:
                    return {"status": "busy", "messages": []}
                replies, summary, *details = result
                lines = details[0] if details else None
                if isinstance(lines, list) and all(isinstance(line, str) for line in lines):
                    lines = [line.strip()[:300] for line in lines[:8] if line.strip()]
                else:
                    lines = None
                # Commit and session validation share a lock: stop cannot race delivery.
                messages = self.deliver(replies)
                session['background_injected'] = True
                session['summary'] = str(summary or '')[:2500]
                if self.records:
                    self.records.record(snapshot, session['summary'], replies, messages)
                return {"status": "commented" if messages else "silent", "messages": messages,
                        "screenshot_subtitles": lines, "analysis_position": snapshot.get('position')}
        finally:
            with self.lock:
                self.busy = False
