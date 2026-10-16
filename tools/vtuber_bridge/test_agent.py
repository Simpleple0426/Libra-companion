import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "third_party" / "Open-LLM-VTuber"))
from src.open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource, ImageData, ImageSource
from agent import LibraAgent


async def collect(agent, value):
    return [output async for output in agent.chat(value)]


class AgentTests(unittest.TestCase):
    def test_screen_and_text_reach_libra(self):
        agent = LibraAgent("http://127.0.0.1:8000")
        agent.client.chat = AsyncMock(return_value=["我在。"])
        outputs = asyncio.run(collect(agent, BatchInput(
            [TextData(TextSource.INPUT, "看这里")],
            [ImageData(ImageSource.SCREEN, "eA==", "image/png")])) )
        agent.client.chat.assert_awaited_once_with("看这里", ("eA==", "image/png"))
        self.assertEqual(outputs[0].display_text.name, "左然")
        self.assertEqual(outputs[0].tts_text, "我在。")

    def test_proactive_prompt_does_not_become_user_memory(self):
        agent = LibraAgent("http://127.0.0.1:8000")
        agent.client.chat = AsyncMock()
        self.assertEqual(asyncio.run(collect(agent, BatchInput(
            [TextData(TextSource.INPUT, "proactive prompt")], metadata={"proactive_speak": True}))), [])
        agent.client.chat.assert_not_awaited()

    def test_interrupt_discards_late_response(self):
        agent = LibraAgent("http://127.0.0.1:8000")
        async def reply(*args):
            agent.handle_interrupt("")
            return ["过时回复"]
        agent.client.chat = reply
        self.assertEqual(asyncio.run(collect(agent, BatchInput(
            [TextData(TextSource.INPUT, "你好")]))), [])
