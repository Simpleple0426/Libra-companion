"""Public composition point for the evidence-backed memory store."""
from .base import *  # re-export stable primitives
from .admin import MemoryAdminMixin
from .core import MemoryCore
from .lmc import LmcMemoryMixin


class MemoryStore(LmcMemoryMixin, MemoryAdminMixin, MemoryCore):
    """Composed store; responsibilities live in focused mixins."""

    pass
