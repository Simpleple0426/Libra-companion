"""Load the three non-RAG canon configurations used on every turn."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path


CORPUS_ROOT = Path(__file__).resolve().parents[3] / "libra" / "zuoran_corpus_v2"


@lru_cache(maxsize=3)
def _load(relative_path: str) -> dict:
    path = CORPUS_ROOT / relative_path
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def style_profile() -> dict:
    return _load("dialogue/style_profile.json")


def emotion_lexicon() -> dict:
    return _load("emotion/character_emotion_lexicon.json")


def mood_pool() -> dict:
    return _load("emotion/mood_pool.json")


def style_prompt() -> str:
    data = style_profile()
    lengths = data.get("sentence_length", {})
    lines = [
        "稳定语言风格（常驻配置）：",
        f"直接程度={data.get('directness', 'medium')}；情绪直白程度={data.get('emotional_explicitness', 'low_to_medium')}；网络用语频率={data.get('internet_slang_frequency', 'very_low')}。",
        f"日常句长={lengths.get('daily', 'short_to_medium')}；认真讨论={lengths.get('serious', 'medium_to_long')}；情绪高点={lengths.get('emotional_peak', 'medium')}。",
    ]
    patterns = data.get("patterns") or []
    structures = data.get("recurring_structures") or []
    avoid = data.get("avoid") or []
    if patterns:
        lines.append("稳定习惯：" + "；".join(patterns[:8]) + "。")
    if structures:
        lines.append("常用反应顺序：" + "；".join(structures[:5]) + "。")
    if avoid:
        lines.append("避免：" + "；".join(avoid) + "。")
    lines.append("该配置约束总体风格；本轮原作 RAG 只提供情境参考，不得覆盖这些人格边界。")
    lines.append("全局表达边界：不模板化安慰，不每句使用爱称，不强行引用旧事，不凭语料宣称已执行现实行动。")
    return "\n".join(lines)
