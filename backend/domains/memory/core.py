"""Composition root for memory write-side responsibilities."""
from .extraction import MemoryExtractionMixin
from .ingestion import MemoryIngestionMixin
from .persistence import MemoryPersistenceMixin


class MemoryCore(MemoryExtractionMixin, MemoryIngestionMixin, MemoryPersistenceMixin):
    """Combines persistence, ingestion and extraction behavior."""

    pass
