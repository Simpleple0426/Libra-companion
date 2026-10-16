"""Read-only retrieval over the user-confirmed Libra reading library."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3] / "libra" / "reading_knowledge"


@lru_cache(maxsize=1)
def _library() -> tuple[dict, list[dict], list[dict]]:
    try:
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        cards = json.loads((ROOT / "knowledge_cards.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, [], []
    quotes = []
    try:
        for line in (ROOT / "verified_quotes.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if item.get("verified") is True:
                    quotes.append(item)
    except (OSError, json.JSONDecodeError):
        quotes = []
    books = {item["book_id"]: item for item in catalog.get("books", [])}
    return books, cards.get("cards", []), quotes


def search(query: str, limit: int = 2) -> list[dict]:
    text = str(query or "").casefold()
    if not text.strip():
        return []
    books, cards, quotes = _library()
    ranked = []
    for card in cards:
        book = books.get(card.get("book_id"))
        if not book:
            continue
        names = [book.get("title", ""), book.get("author", ""), *book.get("alternate_titles", [])]
        title_hit = any(name and str(name).casefold() in text for name in names)
        theme_hits = [
            theme for theme in card.get("themes", [])
            if len(str(theme)) >= 2 and str(theme).casefold() in text
        ]
        score = (100 if title_hit else 0) + len(theme_hits) * 10
        if not score:
            continue
        verified = [item for item in quotes if item.get("book_id") == book["book_id"]]
        ranked.append((score, {"book": book, "card": card, "verified_quotes": verified}))
    ranked.sort(key=lambda item: (-item[0], item[1]["book"]["title"]))
    return [item for _, item in ranked[:max(1, min(limit, 3))]]


def context_for(query: str, limit: int = 2) -> str:
    matches = search(query, limit)
    if not matches:
        return ""
    payload = []
    for item in matches:
        book, card = item["book"], item["card"]
        payload.append({
            "book_id": book["book_id"], "title": book["title"],
            "author": book["author"], "reading_status": book["reading_status"],
            "scope_note": book.get("scope_note"), "summary": card["summary"],
            "themes": card["themes"], "discussion_angles": card["discussion_angles"],
            "verified_quotes": item["verified_quotes"],
        })
    return (
        "\n<reading_knowledge>\n"
        "以下是用户确认你读过的作品及本地内容知识卡。可以准确概括、转述和讨论；"
        "不得把概述冒充原文。只有 verified_quotes 中的内容可以作为逐字引文放进引号；"
        "数组为空时明确以‘我的理解’或作品讨论的方式转述，不得生成伪引文。"
        "reading_status=read 不代表此刻正在重读。\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n</reading_knowledge>"
    )
