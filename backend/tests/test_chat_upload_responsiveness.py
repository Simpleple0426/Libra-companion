import ast
import asyncio
from pathlib import Path
import threading
import unittest
from types import SimpleNamespace

from starlette.concurrency import run_in_threadpool


class ChatUploadResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_generation_leaves_event_loop_available(self):
        source = Path(__file__).parents[1] / 'app/runtime.py'
        node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == 'upload_chat_image_with_caption')
        node.decorator_list = []
        started, release = threading.Event(), threading.Event()

        async def save(*args, **kwargs):
            return {'success': True, 'message': {'media_url': '/uploads/chat/photo.jpg'}}

        def chat(*args, **kwargs):
            started.set()
            if not release.wait(2):
                raise TimeoutError('event loop blocked during photo reply')
            return {'success': True, 'reply_messages': [{'content': 'reply'}]}

        scope = dict(UploadFile=object, File=lambda *a: None, Form=lambda *a: None,
                     Path=Path, UPLOAD_DIR=Path('/uploads'), ChatRequest=SimpleNamespace,
                     _save_uploaded_chat_media=save, _chat_impl=chat,
                     run_in_threadpool=run_in_threadpool)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        task = asyncio.create_task(scope[node.name](file=None, caption='photo', request_id=None))
        try:
            async with asyncio.timeout(1):
                while not started.is_set():
                    await asyncio.sleep(.01)
            # A synchronization request can run while model generation waits.
            await asyncio.sleep(0)
        finally:
            release.set()
        result = await task
        self.assertTrue(result['reply_success'])
        self.assertEqual(result['reply_messages'], [{'content': 'reply'}])
