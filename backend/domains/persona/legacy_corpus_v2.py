"""Compatibility import for the former character-corpus module name.

New production code should import from :mod:`character_corpus`.
"""
from domains.persona.character_corpus import (
    CharacterCorpusStore,
    DOMAINS,
    LEVELS,
    ROOT,
    format_evidence,
    validate_sample,
)

CorpusStore = CharacterCorpusStore

__all__ = [
    'CharacterCorpusStore', 'CorpusStore', 'DOMAINS', 'LEVELS', 'ROOT',
    'format_evidence', 'validate_sample',
]
