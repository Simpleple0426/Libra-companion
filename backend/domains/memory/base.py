"""Single-user, evidence-backed LMC memory primitives.

No import of main, no model/network calls during import, no legacy memory reads.
All mutations use short transactions. Model work happens outside SQLite locks.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import uuid
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol


TOKENIZER_VERSION = 'zh-bigram-v1'
POLICY_VERSION = 'lmc5-native-v2'
RRF_K = 60
SENSITIVE = re.compile(r'病历|诊断|创伤|性生活|身份证|银行卡|家庭暴力|抑郁|自残')
CREDENTIAL = re.compile(r'密码|验证码|私钥|api[_ -]?key|access[_ -]?token', re.I)
SMALLTALK = re.compile(r'^(嗯+|哦+|哈+|好[的呀啊吧]?|谢谢|晚安|早安|你好|在吗)[呀啊呢哦～~！!。\s]*$')
RECALL_CUE = re.compile(r'记得|之前|以前|上次|昨天|那次|后来|继续|结果|进展')
CORRECTION = re.compile(r'不是|不再|纠正|记错|说错|改成|别再|不要再|其实|不对')


def uid(prefix: str) -> str:
    return prefix + '_' + uuid.uuid4().hex


def utc(value=None) -> str:
    moment = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        # Existing application timestamps use the machine's local timezone.
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc).isoformat(timespec='microseconds')


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def tokens(text: str) -> set[str]:
    result = set(re.findall(r'[a-z0-9_]+', text.lower()))
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        result.update(run)
        result.update(run[i:i+2] for i in range(len(run)-1))
    return result


def identity_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if len(t) > 1}


def overlap(a: str, b: str) -> float:
    x, y = identity_tokens(a), identity_tokens(b)
    return len(x & y) / max(1, min(len(x), len(y)))


def content_fingerprint(text: str) -> str:
    """Stable cross-channel dedup key; numbers and CJK content are preserved."""
    normalized = re.sub(r'^\s*\[[^\]\n]{1,40}\]\s*', '', str(text))
    normalized = re.sub(r'[\W_]+', '', normalized.lower(), flags=re.UNICODE)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def rrf_fuse(channels: dict[str, list[str]], *, k: int = RRF_K) -> tuple[dict[str, float], dict[str, dict]]:
    scores: dict[str, float] = {}
    breakdown: dict[str, dict] = {}
    for channel, ids in channels.items():
        for rank, item_id in enumerate(dict.fromkeys(ids), 1):
            contribution = 1.0 / (k + rank)
            scores[item_id] = scores.get(item_id, 0.0) + contribution
            breakdown.setdefault(item_id, {})[channel] = {
                'rank': rank, 'rrf': round(contribution, 6)
            }
    return scores, breakdown


def literal_terms(text: str) -> list[str]:
    """Extract bounded exact-search terms from short names, quotes and codenames."""
    quoted = re.findall(r'[“「『\"\']([^”」』\"\']{2,40})[”」』\"\']', text)
    latin = re.findall(r'\b[A-Za-z][A-Za-z0-9_-]{2,31}\b', text)
    cjk=[]
    stop={'记得','之前','以前','说过','提过','那个','这个','什么','怎么'}
    for run in re.findall(r'[\u3400-\u9fff]{2,24}', text):
        for size in (6,5,4,3):
            cjk.extend(run[i:i+size] for i in range(len(run)-size+1)
                       if run[i:i+size] not in stop)
    return list(dict.fromkeys(quoted + latin + cjk))[:24]


def emotion_coordinate(text: str):
    lexicon = {
        '难过': (-.8, .45), '伤心': (-.9, .55), '委屈': (-.75, .65),
        '焦虑': (-.7, .85), '紧张': (-.55, .85), '生气': (-.8, .9),
        '害怕': (-.8, .9), '疲惫': (-.5, .2), '开心': (.85, .65),
        '高兴': (.8, .65), '期待': (.65, .7), '安心': (.7, .2),
    }
    hits = [point for word, point in lexicon.items() if word in text]
    if not hits:
        return None
    return (sum(x for x, _ in hits) / len(hits), sum(y for _, y in hits) / len(hits))


class ValidationError(ValueError):
    pass


class RevisionConflict(ValidationError):
    pass


class EmbeddingAdapter(Protocol):
    """Optional provider; implementation must honor timeout_seconds. Disabled by default."""
    model_id: str
    dimensions: int

    def embed(self, text: str, *, timeout_seconds: float) -> list[float]: ...


def capture_message(connection, message_id, role, content, source, message_type):
    """Called inside save_message's transaction; no older messages are backfilled."""
    from infrastructure.sqlite.connection import table_exists
    enabled = table_exists(connection, 'memory_config')
    if not enabled or source != 'chat' or message_type != 'text' or not content.strip():
        return
    from infrastructure.sqlite.chat_session_state import current_session
    thread_id = current_session(connection)
    now = utc()
    connection.execute(
        """INSERT INTO raw_experiences
        (experience_id,source_type,source_system,source_id,thread_id,actor,content,occurred_at,ingested_at,metadata_json)
        VALUES (?,'chat_message','libra_chat',?,?,?,?,?,?,?)""",
        (uid('rx'), str(message_id), thread_id, 'libra' if role == 'assistant' else role, content, now, now,
         dumps({'message_id': message_id})),
    )
    from infrastructure.memory_wakeup import notify_after_commit
    notify_after_commit(connection, 'chat')


