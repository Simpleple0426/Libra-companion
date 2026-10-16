import asyncio
import base64
import json
import unittest

import httpx

from client import LibraClient


class ClientTests(unittest.TestCase):
    def test_text_uses_existing_agent_and_filters_media(self):
        def handler(request):
            self.assertEqual(request.url.path, "/chat")
            payload = json.loads(request.content)
            self.assertEqual(payload["message"], "一起看电影吧")
            self.assertEqual(payload["reply_mode"], "text")
            self.assertTrue(payload["request_id"].startswith("vtuber:"))
            return httpx.Response(200, json={"success": True, "reply_messages": [
                {"content": "好。", "message_type": "text"},
                {"content": "sticker.png", "message_type": "sticker"}]})
        result = asyncio.run(LibraClient(transport=httpx.MockTransport(handler)).chat("一起看电影吧"))
        self.assertEqual(result, ["好。"])

    def test_image_is_attached_to_same_turn(self):
        def handler(request):
            self.assertEqual(request.url.path, "/messages/image-with-caption")
            self.assertIn(b'name="caption"', request.content)
            self.assertIn(b"screen.png", request.content)
            self.assertIn(b"image bytes", request.content)
            return httpx.Response(200, json={"success": True, "reply_success": True,
                "reply_messages": [{"content": "看到了。"}]})
        image = "data:image/png;base64," + base64.b64encode(b"image bytes").decode()
        result = asyncio.run(LibraClient(transport=httpx.MockTransport(handler)).chat("看看", (image, "image/png")))
        self.assertEqual(result, ["看到了。"])

    def test_failed_generation_is_not_confused_with_successful_upload(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "success": True, "reply_success": False}))
        with self.assertRaises(RuntimeError):
            asyncio.run(LibraClient(transport=transport).chat("看看", ("eA==", "image/png")))

    def test_remote_image_is_not_fetched(self):
        with self.assertRaises(ValueError):
            asyncio.run(LibraClient().chat("看看", ("https://example.com/a.png", "image/png")))

    def test_sleeping_does_not_invent_a_response(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
            "success": True, "queued_while_sleeping": True}))
        self.assertEqual(asyncio.run(LibraClient(transport=transport).chat("你好")), [])


if __name__ == "__main__":
    unittest.main()
