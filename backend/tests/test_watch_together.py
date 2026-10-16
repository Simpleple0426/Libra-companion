import base64
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from application.watch_together import WatchService
from app.api.watch_together import build_watch_router


class WatchTests(unittest.TestCase):
    def setUp(self):
        data = io.BytesIO()
        Image.new('RGB', (16, 16), 'red').save(data, 'JPEG')
        self.frame = 'data:image/jpeg;base64,' + base64.b64encode(data.getvalue()).decode()
        self.now = 0
        self.generate = Mock(return_value=(["这段很有意思。"], "影片中两人见面。"))
        self.deliver = Mock(side_effect=lambda replies: [{'content': r} for r in replies])
        self.service = WatchService(self.generate, self.deliver, lambda: self.now)
        self.identity = self.service.start('电影', 'normal')['session_id']

    def observe(self, seq=0):
        return self.service.observe(self.identity, seq, self.frame)

    def test_comment_and_cooldown(self):
        self.assertEqual(self.observe()['status'], 'commented')
        self.assertEqual(self.observe(1)['status'], 'watching')
        self.generate.assert_called_once()
        self.assertEqual(self.service.session['summary'], '影片中两人见面。')

    def test_silent_analysis_returns_screenshot_text_and_position(self):
        self.generate.return_value = ([], '摘要', ['  画面原文  ', ''])
        result = self.service.observe(self.identity, 0, self.frame, position=30)
        self.assertEqual(result['status'], 'silent')
        self.assertEqual(result['screenshot_subtitles'], ['画面原文'])
        self.assertEqual(result['analysis_position'], 30)
        self.assertNotIn('screenshot_subtitles', self.observe(1))

    def test_empty_and_missing_recognition_are_distinct(self):
        self.generate.return_value = ([], '', [])
        self.assertEqual(self.observe()['screenshot_subtitles'], [])
        self.now += 121
        self.service.control(self.identity, 'heartbeat')
        self.generate.return_value = ([], '', {'invalid': True})
        self.assertIsNone(self.observe(1)['screenshot_subtitles'])

    def test_retry_cannot_duplicate(self):
        self.observe()
        self.assertEqual(self.observe()['status'], 'duplicate')
        self.deliver.assert_called_once()

    def test_pause_during_generation_suppresses_delivery(self):
        def generate(*args):
            self.service.control(self.identity, 'pause')
            return ['late'], 'summary'
        self.service.generate = generate
        self.assertEqual(self.observe()['status'], 'cancelled')
        self.deliver.assert_not_called()

    def test_replaced_session_suppresses_old_reply(self):
        def generate(*args):
            self.service.start('另一部', 'quiet')
            return ['late'], 'summary'
        self.service.generate = generate
        self.assertEqual(self.observe()['status'], 'cancelled')
        self.deliver.assert_not_called()

    def test_disconnect_expires(self):
        self.now = 91
        self.assertEqual(self.observe()['status'], 'paused')
        self.generate.assert_not_called()

    def test_expired_lease_then_heartbeat_cannot_restore_old_result(self):
        def generate(*args):
            self.now = 91
            self.service.control(self.identity, 'heartbeat')
            return ['late'], 'summary'
        self.service.generate = generate
        self.assertEqual(self.observe()['status'], 'cancelled')

    def test_failure_releases_busy_and_is_rate_limited(self):
        self.generate.side_effect = RuntimeError('failed')
        with self.assertRaises(RuntimeError):
            self.observe()
        self.assertFalse(self.service.busy)
        self.assertEqual(self.observe(1)['status'], 'watching')

    def test_invalid_jpeg_rejected(self):
        with self.assertRaises(ValueError):
            self.service.observe(self.identity, 0, 'data:image/jpeg;base64,eA==')

    def test_empty_reply_is_silence(self):
        self.generate.return_value = ([], 'summary')
        self.assertEqual(self.observe()['status'], 'silent')

    def test_subtitle_evidence_reaches_generator(self):
        cues = [{'start': 10, 'end': 12, 'text': '已经播过的对白'}]
        self.service.observe(self.identity, 0, self.frame, 15, cues, 0)
        snapshot = self.generate.call_args.args[0]
        self.assertEqual(snapshot['subtitles'], cues)
        self.assertEqual(snapshot['position'], 15)

    def test_future_or_stale_subtitles_are_rejected(self):
        for start, end, position in [(10, 20, 15), (0, 5, 700), (10, 9, 15)]:
            with self.subTest(end=end), self.assertRaises(ValueError):
                self.service.observe(self.identity, 0, self.frame, position,
                    [{'start': start, 'end': end, 'text': 'not played'}])
        self.generate.assert_not_called()

    def test_resync_clears_summary_and_rejects_old_request(self):
        self.observe()
        revision = self.service.control(self.identity, 'resync')['revision']
        self.assertEqual(self.service.session['summary'], '')
        self.assertEqual(self.service.observe(self.identity, 1, self.frame, 15, [], 0)['status'], 'cancelled')
        self.assertEqual(self.service.observe(self.identity, 2, self.frame, 15, [], revision)['status'], 'commented')

    def test_resync_during_generation_cancels_old_comment(self):
        def generate(*args):
            self.service.control(self.identity, 'resync')
            return ['late'], 'spoiler'
        self.service.generate = generate
        self.assertEqual(self.observe()['status'], 'cancelled')
        self.deliver.assert_not_called()
        self.assertEqual(self.service.session['summary'], '')

    def test_api_requires_pairing_and_validates_frequency(self):
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / 'token'
            token.write_text('test-secret', encoding='utf-8')
            app = FastAPI()
            app.include_router(build_watch_router(self.service, token))
            client = TestClient(app)
            self.assertEqual(client.get('/watch-together/status').status_code, 401)
            headers = {'Authorization': 'Bearer test-secret'}
            self.assertEqual(client.get('/watch-together/status', headers=headers).status_code, 200)
            self.assertEqual(client.post('/watch-together/start', headers=headers,
                                        json={'frequency': 'invalid'}).status_code, 422)
            response = client.post('/watch-together/observe', headers=headers, json={
                'session_id': self.identity, 'sequence': 0, 'frame': self.frame})
            self.assertEqual(response.json()['status'], 'commented')
