"""Transport for the existing Libra conversation API (no second persona)."""
import base64
import uuid

import httpx


class LibraClient:
    def __init__(self, base_url="http://127.0.0.1:8000", transport=None):
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def chat(self, text, image=None):
        request_id = "vtuber:" + uuid.uuid4().hex
        async with httpx.AsyncClient(timeout=600, transport=self.transport) as client:
            if image is None:
                response = await client.post(self.base_url + "/chat", json={
                    "message": text, "request_id": request_id, "reply_mode": "text"})
            else:
                data, mime = image
                if mime not in {"image/jpeg", "image/png", "image/webp"}:
                    raise ValueError("Unsupported screen image type")
                if data.startswith("data:"):
                    header, data = data.split(",", 1)
                    if header != f"data:{mime};base64":
                        raise ValueError("Image data URI does not match MIME type")
                if len(data) > 14_000_000:
                    raise ValueError("Screen image is too large")
                raw = base64.b64decode(data, validate=True)
                response = await client.post(self.base_url + "/messages/image-with-caption",
                    data={"caption": text, "request_id": request_id, "reply_mode": "text"},
                    files={"file": ("screen." + mime.split("/")[1], raw, mime)})
            response.raise_for_status()
            payload = response.json()
        # Do not retry: the Agent may have committed the turn before a timeout.
        success = payload.get("reply_success") if image else payload.get("success")
        if success is not True:
            raise RuntimeError("Libra did not complete the conversation turn")
        if payload.get("queued_while_sleeping"):
            return []
        messages = payload.get("reply_messages") or []
        if messages:
            return [m["content"] for m in messages
                    if m.get("role", "assistant") == "assistant"
                    and m.get("message_type", "text") in {"text", "voice"}
                    and isinstance(m.get("content"), str) and m["content"].strip()]
        return [s for s in payload.get("replies", []) if isinstance(s, str) and s.strip()]
