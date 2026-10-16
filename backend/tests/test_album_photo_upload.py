import ast
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image, ImageOps


class AlbumPhotoUploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        uploads = root / 'chat'
        thumbnails = root / 'thumbnails'
        uploads.mkdir()
        thumbnails.mkdir()
        self.save = Mock(side_effect=lambda *args, **kwargs: {'id': 1, **kwargs})
        app = FastAPI()
        self.scope = dict(app=app, File=File, Form=Form, UploadFile=UploadFile,
                          HTTPException=HTTPException, Path=Path, uuid=uuid,
                          Image=Image, ImageOps=ImageOps, UPLOAD_DIR=uploads,
                          THUMBNAIL_DIR=thumbnails, create_shared_memory=self.save)
        source = Path(__file__).parents[1] / 'app/runtime.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        functions = [node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name in {'upload_shared_memory_photo', '_make_thumbnail'}]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), self.scope)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        image = io.BytesIO()
        Image.new('RGB', (800, 600), 'blue').save(image, 'PNG')
        self.image = image.getvalue()

    def test_upload_saves_file_thumbnail_and_metadata(self):
        response = self.client.post('/shared-memories/photos',
                                    files={'file': ('photo.png', self.image, 'image/png')},
                                    data={'location_text': ' Shanghai ',
                                          'taken_at': '2026-10-04T12:00:00'})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result['success'])
        memory = result['shared_memory']
        path = self.scope['UPLOAD_DIR'] / Path(memory['media_url']).name
        self.assertEqual(path.read_bytes(), self.image)
        thumbnail = self.scope['THUMBNAIL_DIR'] / f'{path.stem}.jpg'
        with Image.open(thumbnail) as image:
            self.assertEqual(image.size, (720, 540))
        self.assertEqual(memory['location_text'], 'Shanghai')
        self.assertEqual(memory['event_date'], '2026-10-04')
        self.assertEqual(memory['author'], 'user')
        self.assertEqual(self.save.call_args.args[0], 'photo')

    def test_generic_mime_uses_filename(self):
        response = self.client.post('/shared-memories/photos',
                                    files={'file': ('photo.PNG', self.image,
                                                    'application/octet-stream')})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['shared_memory']['media_url'].endswith('.png'))

    def test_unsupported_format_is_rejected(self):
        response = self.client.post('/shared-memories/photos',
                                    files={'file': ('photo.txt', b'hello', 'text/plain')})
        self.assertEqual(response.status_code, 415)
        self.save.assert_not_called()
        self.assertEqual(list(self.scope['UPLOAD_DIR'].iterdir()), [])

    def test_oversized_image_is_rejected(self):
        response = self.client.post('/shared-memories/photos',
                                    files={'file': ('photo.png', b'x' * (12 * 1024 * 1024 + 1),
                                                    'image/png')})
        self.assertEqual(response.status_code, 413)
        self.save.assert_not_called()
        self.assertEqual(list(self.scope['UPLOAD_DIR'].iterdir()), [])


if __name__ == '__main__':
    unittest.main()
