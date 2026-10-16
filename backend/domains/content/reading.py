"""Local book-library bridge backed by the bundled co-reading-kit tools."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from infrastructure.paths import PRIVATE_READING_ROOT


ROOT = Path(__file__).resolve().parents[2]
KIT_ROOT = ROOT / "vendor" / "co-reading-kit"
STATE_DIR = PRIVATE_READING_ROOT
BOOKS_DIR = STATE_DIR / "reading" / "books"
NODE = Path("E:/Libra/node-v22.22.3-win-x64/node.exe")


def _node() -> str:
    return str(NODE if NODE.exists() else "node")


def _run(script: str, *args: str) -> str:
    if not KIT_ROOT.exists():
        raise RuntimeError("共读组件尚未安装")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [_node(), str(KIT_ROOT / "scripts" / script), *args, "--state-dir", str(STATE_DIR)],
        cwd=KIT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "书籍处理失败")
    return result.stdout


def import_book(source: Path, title: str | None = None) -> dict:
    arguments = ["--input", str(source), "--max-chars", "3500"]
    if title:
        arguments.extend(["--title", title])
    _run("import-reading-book.js", *arguments)
    # Discover the imported manifest by source filename/title; the newest one
    # is authoritative because imports are serialized by the API.
    manifests = sorted(BOOKS_DIR.glob("*/manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not manifests:
        raise RuntimeError("书籍导入完成，但未找到书籍索引")
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    _run("build-reading-search-index.js", "--book-id", str(manifest["bookId"]))
    return book_summary(manifests[0].parent.name)


def book_summary(book_id: str) -> dict:
    manifest_path = BOOKS_DIR / book_id / "manifest.json"
    if not manifest_path.exists():
        raise KeyError(book_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = manifest.get("chunks") or []
    progress = _read_progress().get("books", {}).get(book_id, {})
    return {
        "book_id": book_id,
        "title": manifest.get("title") or book_id,
        "author": manifest.get("author") or "",
        "chunk_count": len(chunks),
        "current_chunk_id": progress.get("nextChunkId") or (chunks[0].get("id") if chunks else ""),
        "last_read_at": progress.get("lastReadAt") or "",
    }


def list_books() -> list[dict]:
    if not BOOKS_DIR.exists():
        return []
    values = []
    for item in BOOKS_DIR.iterdir():
        if item.is_dir() and (item / "manifest.json").exists():
            values.append(book_summary(item.name))
    return sorted(values, key=lambda value: value["last_read_at"], reverse=True)


def _read_progress() -> dict:
    path = STATE_DIR / "reading" / "progress.json"
    if not path.exists():
        return {"books": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def current_chunk(book_id: str) -> dict:
    manifest_path = BOOKS_DIR / book_id / "manifest.json"
    if not manifest_path.exists():
        raise KeyError(book_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = manifest.get("chunks") or []
    if not chunks:
        raise RuntimeError("这本书没有可阅读的内容")
    progress = _read_progress().get("books", {}).get(book_id, {})
    wanted = progress.get("nextChunkId")
    index = next((i for i, item in enumerate(chunks) if item.get("id") == wanted), 0)
    return _chunk_payload(book_id, chunks[index], index, len(chunks))


def get_chunk(book_id: str, chunk_id: str) -> dict:
    """Return a specific imported section without changing reading progress."""
    manifest_path = BOOKS_DIR / book_id / "manifest.json"
    if not manifest_path.exists():
        raise KeyError(book_id)
    chunks = json.loads(manifest_path.read_text(encoding="utf-8")).get("chunks") or []
    index = next((i for i, item in enumerate(chunks) if item.get("id") == chunk_id), None)
    if index is None:
        raise KeyError(chunk_id)
    return _chunk_payload(book_id, chunks[index], index, len(chunks))


def list_sections(book_id: str) -> list[dict]:
    """Expose the importer's EPUB/TXT section titles as a compact chapter list."""
    manifest_path = BOOKS_DIR / book_id / "manifest.json"
    if not manifest_path.exists():
        raise KeyError(book_id)
    chunks = json.loads(manifest_path.read_text(encoding="utf-8")).get("chunks") or []
    grouped: list[dict] = []
    for index, item in enumerate(chunks):
        section_title = str(item.get("sectionTitle") or item.get("title") or f"第 {index + 1} 段").strip()
        if not grouped or grouped[-1]["title"] != section_title:
            grouped.append({"title": section_title, "chunks": []})
        grouped[-1]["chunks"].append({
            "chunk_id": str(item.get("id") or ""),
            "index": index,
            "title": str(item.get("title") or section_title),
            "preview": str(item.get("preview") or "")[:160],
        })
    return grouped


def get_section(book_id: str, section_index: int) -> dict:
    """Return an entire chapter, combining its imported display-sized chunks."""
    sections = list_sections(book_id)
    if section_index < 0 or section_index >= len(sections):
        raise KeyError(section_index)
    section = sections[section_index]
    manifest_path = BOOKS_DIR / book_id / "manifest.json"
    chunks = json.loads(manifest_path.read_text(encoding="utf-8")).get("chunks") or []
    ids = {part["chunk_id"] for part in section["chunks"]}
    selected = [item for item in chunks if str(item.get("id") or "") in ids]
    text = "\n\n".join(
        (BOOKS_DIR / book_id / str(item.get("path") or f"chunks/{item['id']}.md"))
        .read_text(encoding="utf-8")
        .strip()
        for item in selected
    ).strip()
    return {
        "chunk_id": selected[0]["id"] if selected else "",
        "index": section_index,
        "total": len(sections),
        "title": section["title"],
        "text": text,
        "section_index": section_index,
        "section_chunk_ids": [item["id"] for item in selected],
    }


def _chunk_payload(book_id: str, item: dict, index: int, total: int) -> dict:
    path = BOOKS_DIR / book_id / str(item.get("path") or f"chunks/{item['id']}.md")
    return {
        "chunk_id": item["id"],
        "index": index,
        "total": total,
        "title": item.get("title") or "",
        "text": path.read_text(encoding="utf-8"),
    }


def advance(book_id: str, chunk_id: str) -> None:
    manifest = json.loads((BOOKS_DIR / book_id / "manifest.json").read_text(encoding="utf-8"))
    chunks = manifest.get("chunks") or []
    index = next((i for i, item in enumerate(chunks) if item.get("id") == chunk_id), 0)
    next_item = chunks[min(index + 1, len(chunks) - 1)]
    path = STATE_DIR / "reading" / "progress.json"
    progress = _read_progress()
    progress.setdefault("books", {})[book_id] = {
        "localBookId": book_id, "localTitle": manifest.get("title") or book_id,
        "lastChunkId": chunk_id, "nextChunkId": next_item["id"],
        "lastReadAt": datetime.now().isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
