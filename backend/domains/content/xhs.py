"""Controlled Xiaohongshu browser bridge backed by the socai CLI."""

from __future__ import annotations

import json
import html
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import hashlib
from io import BytesIO
from PIL import Image
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from html.parser import HTMLParser

from infrastructure.sqlite.database import get_connection
from application.tool_execution import remaining_timeout
from infrastructure.paths import UPLOAD_ROOT, XHS_RUN_ROOT, RUNTIME_ROOT


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOCAI_BIN = PROJECT_ROOT / "third_party" / "socai-cli" / "socai.exe"
XHS_MEDIA_DIR = UPLOAD_ROOT / "xhs"
XHS_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
XHS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com|xhslink\.cn)/"
    r"[^\s<>\]\[\"'，。！？、；：]+",
    re.IGNORECASE,
)
NOTE_PATH_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-zA-Z]+)")
XHS_QUERY_CONTINUATION_RE = re.compile(
    r"^(?:[?&]?(?:xsec_token|xsec_source|source|app_platform|app_version|"
    r"share_from_user_hidden|ignoreEngage|type)=[^\s]+(?:&[^\s]+)*)$",
    re.IGNORECASE,
)


class XhsError(RuntimeError):
    pass


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        name = values.get("property") or values.get("name")
        content = values.get("content", "")
        if name and content:
            self.values[name.lower()] = html.unescape(content).strip()


def extract_xhs_urls(text: str) -> list[str]:
    values: list[str] = []
    for match in XHS_URL_RE.finditer(text or ""):
        value = match.group(0).rstrip("，。！？、；：,.!?;:)")
        if value not in values:
            values.append(value)
    return values[:2]


def join_split_xhs_url_messages(messages: list[str]) -> list[str]:
    """Repair a model split immediately after a Xiaohongshu URL's `?`.

    A query string is transport data, never a user-visible message.
    """
    merged: list[str] = []
    for item in messages:
        value = str(item or "").strip()
        if not value:
            continue
        if XHS_QUERY_CONTINUATION_RE.fullmatch(value):
            if merged and re.search(r"https?://\S+\?$", merged[-1]):
                merged[-1] += value.lstrip("?&")
            # An orphaned token is not meaningful conversation content.
            continue
        merged.append(value)
    return merged


def may_need_search_planning(text: str) -> bool:
    """Broad, non-authorizing gate for the LLM search-intent planner."""
    compact = re.sub(r"\s+", "", text or "").lower()
    return bool(
        re.search(r"小红书|xhs|搜搜|搜索|搜一下|去搜|帮我搜|找找|查查", compact)
    )


def has_explicit_search_authorization(text: str) -> bool:
    """Require the user's current utterance—not model inference—to authorize search."""
    compact = re.sub(r"\s+", "", text or "").lower()
    prefixes = (
        r"(?:可以|能不能|能|可不可以)(?:请你|让你|帮我)?",
        r"我想(?:让|请)你",
        r"(?:请|麻烦你|你帮我|帮我|你去|你上|去)",
        r"(?:搜搜|搜索|搜一下|找找|查查)",
    )
    action = r"(?:去|上|在)?(?:小红书|xhs)?(?:上)?(?:搜索|搜搜|搜|找找|找|看看|查查|查)"
    return any(re.search(rf"^{prefix}{action}", compact) for prefix in prefixes)


def normalize_planned_queries(payload: dict, original_text: str, limit: int = 3) -> list[str]:
    """Validate an LLM plan against the user's explicit authorization."""
    if not isinstance(payload, dict) or not has_explicit_search_authorization(original_text):
        return []
    if payload.get("should_search") is not True or payload.get("intent") != "execute_search":
        return []
    raw = payload.get("queries")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        query = re.sub(r"\s+", " ", str(item or "")).strip(" ，。！？、；：,.!?;:")[:100]
        if not query or re.fullmatch(
            r"(?:了|过|到|的是)?(?:什么|啥|什么东西|啥东西|哪些|哪(?:个|些|篇|条|种))(?:呢|呀|啊|好)?",
            query,
        ):
            continue
        if query not in values:
            values.append(query)
        if len(values) >= max(1, min(limit, 3)):
            break
    return values


def requested_search_query(text: str) -> str | None:
    if extract_xhs_urls(text):
        return None
    compact = re.sub(r"\s+", " ", text or "").strip()
    # Only an explicit request may start an external search.  In particular,
    # questions about Libra's earlier browsing ("你刚才搜了什么") are ordinary
    # conversation, not tool authorization.
    request_prefix = (
        r"(?:(?:可以|能不能|能|可不可以)帮我|我想(?:让|请)你|"
        r"请|麻烦你|你帮我|帮我|你)?"
    )
    patterns = (
        rf"^{request_prefix}(?:去|上|在)?小红书(?:上)?(?:搜索|搜搜|搜|找找|找|看看|看)(?:一下)?[：:，, ]*(.+)",
        rf"^{request_prefix}(?:搜索|搜搜|搜|找找|找|看看|看)(?:一下)?小红书(?:上)?(?:的)?[：:，, ]*(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact, re.IGNORECASE)
        if match:
            query = re.sub(
                r"^(?:搜索|搜搜|搜|找找|找|看看|看)(?:一下)?[：:，, ]*",
                "",
                match.group(1),
            )
            # Keep the search phrase concise when the user continues with a
            # conversational explanation after a polite question ending.
            query = re.split(r"(?:好吗|好不好|可以吗|行吗)[，,。.!！?？ ]*", query, maxsplit=1)[0]
            query = query.strip("，。！？、；：,.!?;: ")
            query = re.sub(r"(?:的)?(?:相关内容|帖子|笔记)$", "", query).strip()
            query = re.sub(r"(?:的)?话题(?:吧|呢|呀|啊)?$", "", query).strip()
            query = re.sub(r"(?:可以吗|行吗|好吗|好不好|吗|吧)$", "", query).strip()
            # A bare interrogative is asking what was searched/viewed.  It is
            # never a meaningful query and must not be sent to Xiaohongshu.
            if re.fullmatch(
                r"(?:了|过|到|的是)?(?:什么|啥|什么东西|啥东西|哪些|哪(?:个|些|篇|条|种))(?:呢|呀|啊|好)?",
                query,
            ):
                return None
            return query[:100] or None
    return None


def _resolve_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=remaining_timeout(15)) as response:
            return response.geturl()
    except Exception:
        return url


def parse_note_reference(url: str) -> tuple[str, str, str]:
    resolved = _resolve_url(url)
    parsed = urllib.parse.urlparse(resolved)
    match = NOTE_PATH_RE.search(parsed.path)
    if not match:
        raise XhsError("链接中没有找到小红书笔记 ID")
    query = urllib.parse.parse_qs(parsed.query)
    token = str((query.get("xsec_token") or [""])[0]).strip()
    if not token:
        raise XhsError("链接缺少 xsec_token，请重新从小红书复制分享链接")
    return match.group(1), token, resolved


def _socai_bin() -> Path:
    configured = os.environ.get("SOCAI_BIN", "").strip()
    path = Path(configured) if configured else DEFAULT_SOCAI_BIN
    if not path.exists():
        raise XhsError(f"socai CLI 未安装：{path}")
    return path


def _parse_cli_json(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        raise XhsError("socai 没有返回内容")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        decoder = json.JSONDecoder()
        for index in sorted(starts):
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise XhsError("socai 返回了无法解析的数据")


def _run_socai(arguments: list[str], timeout: int = 240) -> Any:
    timeout = remaining_timeout(timeout)
    XHS_RUN_ROOT.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        # Do not use PIPE here. The CLI launches Chrome descendants which can
        # inherit pipe handles; after the parent times out, communicate() may
        # then wait forever for those descendants. Temporary files make the
        # timeout independent of inherited handles.
        stdout_file = tempfile.TemporaryFile()
        stderr_file = tempfile.TemporaryFile()
        process = subprocess.Popen(
            [str(_socai_bin()), *arguments],
            cwd=XHS_RUN_ROOT,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            return_code = process.wait(timeout=remaining_timeout(timeout))
        except (subprocess.TimeoutExpired, TimeoutError) as error:
            if os.name == 'nt':
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            if process.poll() is None:
                process.kill()
            raise XhsError("读取小红书超时") from error
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode('utf-8', errors='replace')
        stderr = stderr_file.read().decode('utf-8', errors='replace')
    except subprocess.TimeoutExpired as error:
        raise XhsError("读取小红书超时") from error
    except OSError as error:
        raise XhsError(f"无法启动 socai：{error}") from error
    finally:
        for file in (locals().get('stdout_file'), locals().get('stderr_file')):
            if file is not None:
                file.close()
    if return_code != 0:
        detail = (stderr or stdout).strip()[-800:]
        raise XhsError(detail or f"socai 退出码 {return_code}")
    value = _parse_cli_json(stdout)
    if isinstance(value, dict) and value.get("ok") is False:
        reason = str(value.get("reason") or value.get("error") or "读取失败")
        if reason == "login_required":
            reason = "小红书尚未登录，请在 socai 的独立 Chrome 中扫码登录"
        raise XhsError(reason)
    if isinstance(value, dict) and isinstance(value.get("artifact"), dict):
        artifact_path = Path(str(value["artifact"].get("path") or ""))
        try:
            resolved = (artifact_path if artifact_path.is_absolute() else XHS_RUN_ROOT / artifact_path).resolve()
            if resolved.is_relative_to(RUNTIME_ROOT.resolve()) and resolved.is_file():
                artifact_value = json.loads(resolved.read_text(encoding="utf-8"))
                if _find_note_objects(artifact_value):
                    return artifact_value
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return value


def _find_note_objects(value: Any) -> list[dict]:
    def normalize(item: Any) -> dict | None:
        if not isinstance(item, dict):
            return None
        entity = item.get("entity")
        if isinstance(entity, dict):
            if str(item.get("page_error") or "").startswith("stale_note"):
                return None
            merged = dict(entity)
            for key in ("page_ocr_text", "page_ocr_truncated", "page_url"):
                if key in item:
                    merged[key] = item[key]
            return merged
        return item

    if isinstance(value, list):
        return [normalized for item in value if (normalized := normalize(item)) is not None]
    if not isinstance(value, dict):
        return []
    for key in ("notes", "results", "items", "cards", "data"):
        nested = value.get(key)
        if isinstance(nested, list):
            return [
                normalized
                for item in nested
                if (normalized := normalize(item)) is not None
            ]
        if isinstance(nested, dict):
            found = _find_note_objects(nested)
            if found:
                return found
    return [value] if any(key in value for key in ("note_id", "id", "title")) else []


def _note_identity(note: dict) -> tuple[str, str, str]:
    note_id = str(note.get("note_id") or note.get("id") or "").strip()
    title = str(note.get("title") or note.get("display_title") or "").strip()
    author_value = note.get("author") or note.get("user") or note.get("nickname") or ""
    if isinstance(author_value, dict):
        author = str(author_value.get("nickname") or author_value.get("name") or "").strip()
    else:
        author = str(author_value).strip()
    return note_id, title, author


def _save_note(note: dict, token: str = "", canonical_url: str = "") -> None:
    note_id, title, author = _note_identity(note)
    if not note_id:
        return
    now = datetime.now().isoformat()
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO xhs_notes
            (note_id,xsec_token,canonical_url,title,author,content_json,fetched_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(note_id) DO UPDATE SET
            xsec_token=CASE WHEN excluded.xsec_token<>'' THEN excluded.xsec_token ELSE xhs_notes.xsec_token END,
            canonical_url=CASE WHEN excluded.canonical_url<>'' THEN excluded.canonical_url ELSE xhs_notes.canonical_url END,
            title=excluded.title, author=excluded.author,
            content_json=excluded.content_json, fetched_at=excluded.fetched_at,
            updated_at=excluded.updated_at
        """,
        (
            note_id, token, canonical_url, title[:300], author[:200],
            json.dumps(note, ensure_ascii=False), now, now,
        ),
    )
    connection.commit()
    connection.close()


def _cached_note(note_id: str, max_age: timedelta = timedelta(hours=6)) -> dict | None:
    connection = get_connection()
    row = connection.execute(
        "SELECT content_json,fetched_at FROM xhs_notes WHERE note_id=?", (note_id,)
    ).fetchone()
    connection.close()
    if not row:
        return None
    try:
        if datetime.now() - datetime.fromisoformat(row["fetched_at"]) > max_age:
            return None
        value = json.loads(row["content_json"])
        if not isinstance(value, dict):
            return None
        # Older HTML previews were stored as full notes, including login pages.
        if value.get("_preview_only") or set(value) <= {
            "note_id", "title", "author", "content", "cover_url", "url"
        }:
            return None
        return value
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _first_image_url(note: dict) -> str:
    for key in ("cover_url", "cover", "image_url"):
        value = note.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    images = note.get("images") or note.get("image_list") or []
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.startswith("http"):
                return image
            if isinstance(image, dict):
                for key in ("url", "url_default", "url_pre", "cover_url"):
                    value = image.get(key)
                    if isinstance(value, str) and value.startswith("http"):
                        return value
    video = note.get("video")
    if isinstance(video, dict):
        for key in ("cover_url", "cover", "image"):
            value = video.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    return ""


def image_urls(note: dict, limit: int = 12) -> list[str]:
    """Collect all image URLs returned by socai, in note order."""
    found: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in found:
            found.append(value)

    for key in ("cover_url", "cover", "image_url"):
        add(note.get(key))
    images = note.get("images") or note.get("image_list") or []
    if isinstance(images, list):
        for item in images:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                for key in ("url", "url_default", "url_pre", "cover_url", "original"):
                    add(item.get(key))
                    if found and len(found) >= limit:
                        return found[:limit]
    video = note.get("video")
    if isinstance(video, dict):
        for key in ("cover_url", "cover", "image"):
            add(video.get(key))
    return found[:limit]


def cache_image_urls(urls: list[str], limit: int = 12) -> list[Path]:
    """Download trusted XHS images for stable UI display and model vision input."""
    paths: list[Path] = []
    for url in urls[:limit]:
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            if not (host == "xhscdn.com" or host.endswith(".xhscdn.com")
                    or host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")):
                continue
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
            target = XHS_MEDIA_DIR / f"{digest}-jpeg.jpg"
            if not target.exists():
                request = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124 Safari/537.36",
                    "Referer": "https://www.xiaohongshu.com/",
                })
                with urllib.request.urlopen(request, timeout=remaining_timeout(20)) as response:
                    content_type = response.headers.get_content_type()
                    if not content_type.startswith("image/"):
                        continue
                    data = response.read(12_000_001)
                if not data or len(data) > 12_000_000:
                    continue
                with Image.open(BytesIO(data)) as source:
                    source.convert("RGB").save(target, format="JPEG", quality=92)
            paths.append(target)
        except (OSError, ValueError, urllib.error.URLError):
            continue
    return paths

def _note_summary(note: dict) -> str:
    value = str(
        note.get("content")
        or note.get("desc")
        or note.get("description")
        or note.get("page_ocr_text")
        or ""
    )
    return re.sub(r"\s+", " ", value).strip()[:220]


def preview_from_note(
    note: dict,
    *,
    canonical_url: str = "",
    original_url: str = "",
    comment: str = "",
) -> dict:
    note_id, title, author = _note_identity(note)
    url = str(note.get("url") or note.get("note_url") or canonical_url or original_url)
    return {
        "note_id": note_id,
        "title": title or "小红书笔记",
        "author": author,
        "summary": _note_summary(note),
        "cover_url": _first_image_url(note),
        "image_urls": image_urls(note),
        "url": url,
        "original_url": original_url or url,
        "comment": comment.strip()[:2000],
    }


def cached_image_paths_for_text(text: str, limit: int = 12) -> list[Path]:
    urls: list[str] = []
    for original_url in extract_xhs_urls(text):
        try:
            note_id, _, _ = parse_note_reference(original_url)
            note = _cached_note(note_id, max_age=timedelta(days=30))
            if note:
                urls.extend(image_urls(note, limit=limit))
        except XhsError:
            continue
    return cache_image_urls(list(dict.fromkeys(urls)), limit=limit)


def preview_links(text: str, *, use_cache: bool = True) -> dict:
    result = read_links(text, use_cache=use_cache, ocr=False)
    previews = [
        preview_from_note(
            item["note"],
            canonical_url=str(item.get("canonical_url") or ""),
            original_url=str(item.get("original_url") or ""),
        )
        for item in result.get("notes", [])
        if isinstance(item, dict) and isinstance(item.get("note"), dict)
    ]
    return {**result, "previews": previews}


def cached_preview_for_url(url: str, comment: str = "") -> dict | None:
    try:
        note_id, _, canonical_url = parse_note_reference(url)
    except XhsError:
        # Assistant replies can occasionally preserve the note URL while
        # omitting its temporary xsec_token. Search results are already cached
        # by note id, so use that trusted copy instead of rendering an empty
        # card or performing another browser read.
        match = re.search(
            r"/(?:explore|discovery/item)/([0-9a-zA-Z]+)",
            url,
            re.IGNORECASE,
        )
        if match is None:
            return None
        note_id = match.group(1)
        canonical_url = url
    note = _cached_note(note_id, max_age=timedelta(days=30))
    if note is None:
        return None
    return preview_from_note(
        note,
        canonical_url=canonical_url,
        original_url=url,
        comment=comment,
    )


def fast_preview_links(text: str) -> dict:
    previews: list[dict] = []
    errors: list[dict] = []
    for original_url in extract_xhs_urls(text):
        try:
            note_id, token, canonical_url = parse_note_reference(original_url)
            request = urllib.request.Request(
                canonical_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                    "Referer": "https://www.xiaohongshu.com/",
                },
            )
            with urllib.request.urlopen(request, timeout=remaining_timeout(20)) as response:
                page = response.read(1_500_000).decode("utf-8", "replace")
            parser = _MetaParser()
            parser.feed(page)
            title = parser.values.get("og:title") or parser.values.get("twitter:title") or "小红书笔记"
            summary = parser.values.get("og:description") or parser.values.get("description") or ""
            cover = parser.values.get("og:image") or parser.values.get("twitter:image") or ""
            author = parser.values.get("og:site_name") or ""
            note = {
                "_preview_only": True,
                "note_id": note_id,
                "title": title,
                "author": author,
                "content": summary,
                "cover_url": cover,
                "url": canonical_url,
            }
            _save_note(note, token, canonical_url)
            previews.append(
                preview_from_note(
                    note,
                    canonical_url=canonical_url,
                    original_url=original_url,
                )
            )
        except Exception as error:
            errors.append({"url": original_url, "error": str(error)[:500]})
    return {"success": bool(previews), "previews": previews, "errors": errors}


def read_links(text: str, *, use_cache: bool = True, ocr: bool = True) -> dict:
    results: list[dict] = []
    errors: list[dict] = []
    for url in extract_xhs_urls(text):
        try:
            note_id, token, canonical_url = parse_note_reference(url)
            note = _cached_note(note_id) if use_cache else None
            if note is None:
                arguments = [
                    "xhs", "get-notes", "--note", f"{note_id}={token}",
                    "--num-comments", "6",
                ]
                if ocr:
                    arguments.append("--ocr")
                raw = _run_socai(arguments, timeout=90 if not ocr else 240)
                notes = _find_note_objects(raw)
                if not notes:
                    raise XhsError("没有读取到笔记正文")
                note = notes[0]
                _save_note(note, token, canonical_url)
            results.append({"original_url": url, "canonical_url": canonical_url, "note": note})
        except XhsError as error:
            errors.append({"url": url, "error": str(error)})
    return {"success": bool(results), "notes": results, "errors": errors}


def search(query: str, *, source: str = "chat", num_notes: int = 6) -> dict:
    clean_query = re.sub(r"\s+", " ", query).strip()[:100]
    if not clean_query:
        raise XhsError("搜索词不能为空")
    status = "success"
    try:
        raw = _run_socai(
            ["xhs", "search", clean_query, "--num-notes", str(max(1, min(num_notes, 10))),
             "--num-comments", "4"],
            timeout=120,
        )
        for note in _find_note_objects(raw):
            _save_note(note)
    except XhsError as error:
        raw = {"error": str(error)}
        status = "failed"
    connection = get_connection()
    connection.execute(
        "INSERT INTO xhs_search_runs(query,result_json,source,status,created_at) VALUES(?,?,?,?,?)",
        (clean_query, json.dumps(raw, ensure_ascii=False), source[:40], status, datetime.now().isoformat()),
    )
    connection.commit()
    connection.close()
    if status == "failed":
        raise XhsError(str(raw["error"]))
    return {"success": True, "query": clean_query, "result": raw}


def shareable_notes(search_result: dict, limit: int = 5) -> list[dict]:
    notes = _find_note_objects(search_result.get("result"))
    if not notes:
        return []
    connection = get_connection()
    shared_ids = {
        str(row["note_id"])
        for row in connection.execute("SELECT note_id FROM xhs_shared_notes").fetchall()
    }
    connection.close()
    values: list[dict] = []
    for note in notes:
        note_id, title, author = _note_identity(note)
        if not note_id or note_id in shared_ids:
            continue
        token = str(note.get("xsec_token") or note.get("xsecToken") or "").strip()
        url = str(note.get("url") or note.get("note_url") or "").strip()
        if not url and token:
            url = (
                f"https://www.xiaohongshu.com/explore/{note_id}?"
                + urllib.parse.urlencode({"xsec_token": token, "xsec_source": "pc_search"})
            )
        values.append({
            "note_id": note_id,
            "title": title,
            "author": author,
            "url": url,
            "content": note,
        })
        if len(values) >= limit:
            break
    return values


def mark_shared(note_id: str, query: str, source_message_id: int | None = None) -> None:
    clean_id = str(note_id or "").strip()
    if not clean_id:
        return
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO xhs_shared_notes(note_id,search_query,shared_at,source_message_id)
        VALUES(?,?,?,?)
        ON CONFLICT(note_id) DO UPDATE SET
            search_query=excluded.search_query,
            shared_at=excluded.shared_at,
            source_message_id=COALESCE(excluded.source_message_id,xhs_shared_notes.source_message_id)
        """,
        (clean_id, query[:100], datetime.now().isoformat(), source_message_id),
    )
    connection.commit()
    connection.close()


def context_json(value: dict, max_chars: int = 14000) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return encoded if len(encoded) <= max_chars else encoded[:max_chars] + "…"
