"""Read-only retrieval over the user-confirmed Libra movie library."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3] / "libra" / "movie_knowledge"


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
    movies = {item["movie_id"]: item for item in catalog.get("movies", [])}
    return movies, cards.get("cards", []), quotes


def search(query: str, limit: int = 2) -> list[dict]:
    text = str(query or "").casefold()
    if not text.strip():
        return []
    movies, cards, quotes = _library()
    ranked = []
    for card in cards:
        movie = movies.get(card.get("movie_id"))
        if not movie or movie.get("identity_status") not in {"resolved", "assumed"}:
            continue
        names = [movie.get("title", ""), movie.get("original_title", ""), *movie.get("alternate_titles", [])]
        title_hit = any(name and str(name).casefold() in text for name in names)
        theme_hits = [
            theme for theme in card.get("themes", [])
            if len(str(theme)) >= 2 and str(theme).casefold() in text
        ]
        score = (100 if title_hit else 0) + len(theme_hits) * 10
        if score:
            verified = [item for item in quotes if item.get("movie_id") == movie["movie_id"]]
            ranked.append((score, {"movie": movie, "card": card, "verified_quotes": verified}))
    ranked.sort(key=lambda item: (-item[0], item[1]["movie"]["title"]))
    return [item for _, item in ranked[:max(1, min(limit, 3))]]


def context_for(query: str, limit: int = 2) -> str:
    matches = search(query, limit)
    if not matches:
        return ""
    payload = []
    for item in matches:
        movie, card = item["movie"], item["card"]
        payload.append({
            "movie_id": movie["movie_id"], "title": movie["title"],
            "original_title": movie.get("original_title"), "year": movie.get("year"),
            "viewing_status": movie["status"], "identity_note": movie.get("identity_note"),
            "summary": card["summary"], "themes": card["themes"],
            "discussion_angles": card["discussion_angles"],
            "verified_quotes": item["verified_quotes"],
        })
    return (
        "\n<movie_knowledge>\n"
        "以下是用户确认你已经看过的电影及本地知识卡；看过的电影仍然可以重看。"
        "可以概括影片内容或结合已知内容谈看法，但 reading knowledge 不证明他此刻正在播放该片。"
        "但只有 verified_quotes 中的内容可以作为逐字台词放进引号；数组为空时不得生成伪台词。\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n</movie_knowledge>"
    )
