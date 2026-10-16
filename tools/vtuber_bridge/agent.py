"""Open-LLM-VTuber v1.2.1 custom Agent; memory stays with Libra."""
from loguru import logger
from src.open_llm_vtuber.agent.agents.agent_interface import AgentInterface
from src.open_llm_vtuber.agent.output_types import Actions, DisplayText, SentenceOutput

from client import LibraClient


class LibraAgent(AgentInterface):
    def __init__(self, base_url):
        self.client = LibraClient(base_url)
        self._generation = 0

    async def chat(self, input_data):
        # Upstream proactive prompts are not user messages. A dedicated movie
        # observation endpoint is required before enabling that separate flow.
        if (input_data.metadata or {}).get("proactive_speak"):
            logger.info("Libra bridge: automatic observations are not enabled")
            return
        text = "\n".join(t.content for t in input_data.texts
                         if getattr(t.source, "value", t.source) == "input").strip()
        if not text:
            return
        images = input_data.images or []
        screen = next((i for i in reversed(images)
                       if getattr(i.source, "value", i.source) == "screen"), None)
        selected = screen or (images[-1] if images else None)
        generation = self._generation
        try:
            replies = await self.client.chat(text,
                (selected.data, selected.mime_type) if selected else None)
        except Exception as error:
            logger.warning("Libra bridge request failed: {}", type(error).__name__)
            yield SentenceOutput(DisplayText("连接未完成，请检查左然后端；不要重复发送。", name="连接状态"), "", Actions())
            return
        for reply in replies:
            if generation != self._generation:
                return
            yield SentenceOutput(DisplayText(reply, name="左然"), reply, Actions())

    def handle_interrupt(self, heard_response):
        # Stop delivering this response. The existing HTTP API cannot cancel
        # generation or roll back an already committed memory turn.
        self._generation += 1

    def set_memory_from_history(self, conf_uid, history_uid):
        # Frontend histories must never reset or import over Libra's memory.
        pass
