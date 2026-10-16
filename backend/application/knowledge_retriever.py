"""Unified orchestration over independent, evidence-scoped knowledge stores."""
from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import logging
from time import perf_counter
from typing import Callable


_logger = logging.getLogger(__name__)


@dataclass
class KnowledgeBundle:
    character_evidence: list[dict] = field(default_factory=list)
    character_reference: str = ""
    character_situations: list[dict] = field(default_factory=list)
    context: str = ""
    degraded_components: list[str] = field(default_factory=list)


class KnowledgeRetriever:
    """Coordinates retrieval without erasing each source's authority boundary."""

    def __init__(self, *, memory_store, character_store, shared_history_store,
                 evidence_formatter: Callable, reading_context: Callable | None = None,
                 movie_context: Callable | None = None, world_context: Callable | None = None, situation_model: Callable | None = None):
        self.memory_store = memory_store
        self.character_store = character_store
        self.shared_history_store = shared_history_store
        self.evidence_formatter = evidence_formatter
        self.reading_context = reading_context
        self.movie_context = movie_context
        self.world_context = world_context
        self.situation_model = situation_model

    def personal_memory(self, query: str, *, thread_id=None, recent_messages=(),
                        budget=2200, limit=4, graph_hops=2,
                        query_expansion=False, emotion_resonance=True,
                        literal_raw=True, adaptive_search=True, query_weights=None, channel_weights=None, query_plan=None,
                        spontaneous=True) -> dict:
        """Shared recall configuration for user messages and proactive events."""
        query = str(query or "")
        return self.memory_store.recall(
            query, thread_id=thread_id, recent_messages=recent_messages,
            budget=budget, limit=limit, allowed_scopes=('user', 'self', 'shared'),
            graph_hops=graph_hops, query_expansion=query_expansion,
            emotion_resonance=emotion_resonance, literal_raw=literal_raw,
            adaptive_search=adaptive_search, query_weights=query_weights, channel_weights=channel_weights, query_plan=query_plan,
            spontaneous=spontaneous,
        )

    def supporting_knowledge(self, query: str, *, thread_id=None, recent_messages=(),
                             relationship_stage='established_partner', intent=None,
                             appraisal=None, enabled=True, context_budget=9000, query_plan=None, proactive=False,
                             user_message_only=False, include_shared_history=False,
                             character_only=False) -> KnowledgeBundle:
        bundle = KnowledgeBundle()
        if not enabled:
            return bundle
        from domains.memory.recall_queries import plan, ranked_search
        query_plan = query_plan or plan(query, recent_messages)
        def character():
            # Keep the dependent situation -> evidence steps in one branch.
            result = KnowledgeBundle()
            character_plan = list(query_plan)
            if self.situation_model:
                try:
                    from domains.persona.situation import character_situations
                    result.character_situations = character_situations(
                        query, recent_messages, query_plan, self.situation_model, proactive,
                        emotional_only=user_message_only)
                    character_plan.extend(result.character_situations)
                except Exception:
                    result.degraded_components.append('character_situation_unavailable')
            if user_message_only or character_only:
                if not result.character_situations:
                    return result
                character_plan = result.character_situations
            try:
                result.character_evidence = ranked_search(lambda text: self.character_store.search(
                    text, limit=6, relationship_stage=relationship_stage,
                    intent=intent, appraisal=appraisal or {},
                ), query, character_plan, limit=6)
                result.character_reference = self.evidence_formatter(result.character_evidence)
            except Exception:
                result.degraded_components.append('character_evidence_unavailable')
            return result

        if user_message_only or character_only:
            return character()

        blocks = []
        sources = [
            ('world_event_knowledge_unavailable', lambda: self.world_context(query) if self.world_context else ''),
            ('reading_knowledge_unavailable', lambda: self.reading_context(query) if self.reading_context else ''),
            ('movie_knowledge_unavailable', lambda: self.movie_context(query) if self.movie_context else ''),
        ]
        if include_shared_history:
            sources.insert(0, ('shared_history_unavailable', lambda: self.shared_history_store.context_for(
                query, thread_id=thread_id, recent_messages=recent_messages, query_plan=query_plan)))
        def timed(loader):
            started = perf_counter()
            try:
                return loader(), None, perf_counter() - started
            except Exception as error:
                return None, error, perf_counter() - started

        started = perf_counter()
        timings = {}
        # Per-call ownership ensures no work outlives its turn. Each task gets
        # its own Context, preserving model tracing without sharing Context.run.
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix='libra-knowledge') as executor:
            character_future = executor.submit(copy_context().run, timed, character)
            futures = [(name, executor.submit(copy_context().run, timed, loader))
                       for name, loader in sources]
            bundle, error, timings['character'] = character_future.result()
            if error is not None:
                raise error
            used = 0
            # Consume in source priority order, never completion order: the
            # same evidence wins the context budget even when timings vary.
            for degraded_name, future in futures:
                value, error, timings[degraded_name] = future.result()
                try:
                    if error is not None:
                        raise error
                    block = str(value or '')
                except Exception:
                    bundle.degraded_components.append(degraded_name)
                    continue
                if block and used + len(block) <= max(1000, context_budget):
                    blocks.append(block)
                    used += len(block)
        bundle.context = ''.join(blocks)
        _logger.info('supporting_knowledge elapsed_ms=%.1f branch_ms=%s',
                     (perf_counter() - started) * 1000,
                     {name: round(seconds * 1000, 1) for name, seconds in timings.items()})
        return bundle
