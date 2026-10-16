"""Searchable, source-traceable shared history derived from reviewed story scenes."""

from __future__ import annotations

import json
import re
import sqlite3
import hashlib
from contextlib import contextmanager
from pathlib import Path

from domains.memory.store import tokens
from domains.persona.reviewed_history import REVIEWED_SOURCE, import_events, event_excerpts
from infrastructure.embeddings.local import normalized


DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "libra" / "zuoran_corpus_v2" / "reviewed" / "story_evidence.jsonl"
)
PROJECT_LIBRA = Path(__file__).resolve().parents[3] / "libra"
DEFAULT_TRANSCRIPT_ROOTS = (PROJECT_LIBRA / "个人线", PROJECT_LIBRA / "卡面")


class CanonicalHistoryStore:
    def __init__(self, database_path: str | Path, embedding_adapter=None):
        self.database_path = Path(database_path)
        self.embedding_adapter = embedding_adapter

    @contextmanager
    def connect(self):
        from infrastructure.sqlite.connection import connect
        connection = connect(self.database_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS canonical_shared_history (
                history_id TEXT PRIMARY KEY, relationship_stage TEXT NOT NULL,
                summary TEXT NOT NULL, source_path TEXT NOT NULL,
                line_start INTEGER, line_end INTEGER, payload_json TEXT NOT NULL)"""
            )
            connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS canonical_shared_history_fts
                USING fts5(history_id UNINDEXED, search_text)"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS canonical_shared_history_chunks (
                chunk_id TEXT PRIMARY KEY, source_path TEXT NOT NULL,
                line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
                content TEXT NOT NULL)"""
            )
            connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS canonical_shared_history_chunks_fts
                USING fts5(chunk_id UNINDEXED, search_text)"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS canonical_shared_history_embeddings (
                history_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, dimensions INTEGER NOT NULL,
                content_hash TEXT NOT NULL, vector_json TEXT NOT NULL)"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS canonical_shared_history_chunk_embeddings (
                chunk_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, dimensions INTEGER NOT NULL,
                content_hash TEXT NOT NULL, vector_json TEXT NOT NULL)"""
            )

    def _refresh_table(self, source_table, id_column, text_sql, embedding_table, batch_size):
        if self.embedding_adapter is None:
            return 0
        model_id=str(self.embedding_adapter.model_id);dimensions=int(self.embedding_adapter.dimensions)
        with self.connect() as connection:
            rows=connection.execute(f"SELECT {id_column},{text_sql} FROM {source_table} ORDER BY {id_column}").fetchall()
            existing={row[0]:row[1] for row in connection.execute(
                f"SELECT {id_column},content_hash FROM {embedding_table} WHERE model_id=? AND dimensions=?",
                (model_id,dimensions))}
        pending=[]
        for row in rows:
            record_id=str(row[0]);text=str(row[1] or '')
            digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
            if existing.get(record_id)!=digest:pending.append((record_id,digest,text))
        embedded=0
        for start in range(0,len(pending),max(1,batch_size)):
            batch=pending[start:start+max(1,batch_size)]
            if hasattr(self.embedding_adapter,'embed_many'):
                vectors=self.embedding_adapter.embed_many([item[2] for item in batch],timeout_seconds=180)
            else:
                vectors=[self.embedding_adapter.embed(item[2],timeout_seconds=30) for item in batch]
            with self.connect() as connection:
                for (record_id,digest,_),vector in zip(batch,vectors):
                    unit=normalized(vector)
                    if len(unit)!=dimensions:continue
                    connection.execute(f"INSERT OR REPLACE INTO {embedding_table} VALUES (?,?,?,?,?)",
                        (record_id,model_id,dimensions,digest,json.dumps(unit,separators=(',',':'))))
                    embedded+=1
        return embedded

    def refresh_embeddings(self, batch_size=64):
        scenes=self._refresh_table('canonical_shared_history','history_id',
            "summary || ' ' || payload_json",'canonical_shared_history_embeddings',batch_size)
        chunks=0 if self._uses_event_excerpts() else self._refresh_table('canonical_shared_history_chunks','chunk_id',
            "content || ' ' || source_path",'canonical_shared_history_chunk_embeddings',batch_size)
        return {'enabled':self.embedding_adapter is not None,'scenes':scenes,'chunks':chunks}

    def _dense_scores(self, query, embedding_table, id_column):
        if self.embedding_adapter is None:return None
        try:
            query_vector=normalized(self.embedding_adapter.embed(query,timeout_seconds=12))
            with self.connect() as connection:
                rows=connection.execute(
                    f"SELECT {id_column},vector_json FROM {embedding_table} WHERE model_id=? AND dimensions=?",
                    (str(self.embedding_adapter.model_id),int(self.embedding_adapter.dimensions))).fetchall()
            if not rows:
                return None
            scores={}
            for row in rows:
                score=sum(a*b for a,b in zip(query_vector,json.loads(row[1])))
                if score>=.30:scores[str(row[0])]=score
            return scores
        except (TimeoutError,ValueError,TypeError,sqlite3.Error):
            return None

    def import_reviewed(self, source: str | Path = REVIEWED_SOURCE) -> dict:
        source_path = Path(source)
        if source_path.suffix.lower() == ".json":
            return import_events(self, source_path)
        rows = []
        for line in source_path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            evidence = json.loads(line)
            if evidence.get("review_status") != "approved":
                continue
            reference = evidence.get("source_ref") or {}
            path = str(reference.get("path") or "")
            # Only user-designated personal-route/card transcripts become
            # shared history. Other future evidence remains character-only.
            if not (path.startswith("libra/个人线/") or path.startswith("libra/卡面/")):
                continue
            history_id = "canon_history_" + str(evidence["id"])
            payload = {
                "history_id": history_id,
                "status": "canonical_shared_past",
                "participants": ["user", "zuoran"],
                "summary": str(evidence.get("context") or "").strip(),
                "relationship_stage": str(
                    (evidence.get("applicability") or {}).get("relationship_stage")
                    or "unknown"
                ),
                "tags": list(evidence.get("tags") or []),
                "evidence_quote": str(evidence.get("evidence_quote") or "").strip(),
                "source_ref": reference,
                "temporal_scope": "past_unspecified_date",
            }
            searchable = " ".join(
                [payload["summary"], payload["evidence_quote"], *payload["tags"], path]
            )
            rows.append((history_id, payload, searchable))
        self.initialize()
        with self.connect() as connection:
            connection.execute("DELETE FROM canonical_shared_history")
            connection.execute("DELETE FROM canonical_shared_history_fts")
            for history_id, payload, searchable in rows:
                reference = payload["source_ref"]
                connection.execute(
                    "INSERT INTO canonical_shared_history VALUES (?,?,?,?,?,?,?)",
                    (
                        history_id, payload["relationship_stage"], payload["summary"],
                        str(reference.get("path") or ""), reference.get("line_start"),
                        reference.get("line_end"),
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                connection.execute(
                    "INSERT INTO canonical_shared_history_fts VALUES (?,?)",
                    (history_id, " ".join(sorted(tokens(searchable)))),
                )
        return {"records": len(rows), "source": str(source_path)}

    def import_transcripts(self, roots=DEFAULT_TRANSCRIPT_ROOTS) -> dict:
        """Index all non-empty user-designated transcripts in bounded line chunks."""
        self.initialize()
        if self._uses_event_excerpts():
            return {"files": 0, "chunks": 0, "skipped": "reviewed_event_sources_only"}
        chunks = []
        files = []
        for root_value in roots:
            root = Path(root_value)
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.md")):
                text = path.read_text(encoding="utf-8-sig")
                if not text.strip():
                    continue
                files.append(path)
                lines = text.splitlines()
                start = 0
                while start < len(lines):
                    end = min(len(lines), start + 45)
                    content = "\n".join(lines[start:end]).strip()
                    if content:
                        try:
                            relative = path.relative_to(PROJECT_LIBRA.parent).as_posix()
                        except ValueError:
                            relative = path.as_posix()
                        chunk_id = f"transcript_{len(chunks) + 1:05d}"
                        chunks.append((chunk_id, relative, start + 1, end, content))
                    if end >= len(lines):
                        break
                    start = max(start + 1, end - 8)
        self.initialize()
        with self.connect() as connection:
            connection.execute("DELETE FROM canonical_shared_history_chunks")
            connection.execute("DELETE FROM canonical_shared_history_chunks_fts")
            for chunk_id, path, line_start, line_end, content in chunks:
                connection.execute(
                    "INSERT INTO canonical_shared_history_chunks VALUES (?,?,?,?,?)",
                    (chunk_id, path, line_start, line_end, content),
                )
                connection.execute(
                    "INSERT INTO canonical_shared_history_chunks_fts VALUES (?,?)",
                    (chunk_id, " ".join(sorted(tokens(content + " " + path)))),
                )
        return {"files": len(files), "chunks": len(chunks)}

    def search(self, query: str, limit: int = 5) -> list[dict]:
        parts = sorted(tokens(query), key=lambda value: (-len(value), value))[:36]
        if not parts and not query.strip():
            return []
        expression = " OR ".join(
            '"' + part.replace('"', '""') + '"' for part in parts
        )
        requested=max(1,min(limit,8))
        with self.connect() as connection:
            rows = [] if not parts else connection.execute(
                """SELECT h.payload_json,bm25(canonical_shared_history_fts) rank
                FROM canonical_shared_history_fts f
                JOIN canonical_shared_history h ON h.history_id=f.history_id
                WHERE canonical_shared_history_fts MATCH ?
                ORDER BY rank LIMIT ?""",
                (expression, max(24,requested*5)),
            ).fetchall()
        ranked={json.loads(row[0])['history_id']:(json.loads(row[0]),1/(1+index),0.0)
                for index,row in enumerate(rows)}
        dense=self._dense_scores(query,'canonical_shared_history_embeddings','history_id')
        # Canonical history must not be injected on a weak lexical coincidence.
        # When the dense index is available it acts as a semantic relevance gate.
        if dense is not None:
            ranked={record_id:value for record_id,value in ranked.items() if record_id in dense}
        missing=[] if dense is None else [record_id for record_id in dense if record_id not in ranked]
        if missing:
            with self.connect() as connection:
                placeholders=','.join('?' for _ in missing)
                for row in connection.execute(f"SELECT history_id,payload_json FROM canonical_shared_history WHERE history_id IN ({placeholders})",missing):
                    ranked[row[0]]=(json.loads(row[1]),0.0,dense[row[0]])
        for record_id,(payload,lexical,_) in list(ranked.items()):
            ranked[record_id]=(payload,lexical,0.0 if dense is None else dense.get(record_id,0.0))
        ordered=sorted(ranked.values(),key=lambda item:item[1]+item[2]*1.5,reverse=True)
        return [item[0] for item in ordered[:requested]]

    def _uses_event_excerpts(self):
        with self.connect() as connection:
            row = connection.execute("SELECT payload_json FROM canonical_shared_history LIMIT 1").fetchone()
        return bool(row and "excerpt_ids" in json.loads(row[0]))

    def search_transcripts(self, query: str, limit: int = 2) -> list[dict]:
        if self._uses_event_excerpts():
            return event_excerpts(self, self.search(query, limit), query)[:limit]
        parts = sorted(tokens(query), key=lambda value: (-len(value), value))[:36]
        if not parts and not query.strip():
            return []
        expression = " OR ".join(
            '"' + part.replace('"', '""') + '"' for part in parts
        )
        requested=max(1,min(limit,3))
        with self.connect() as connection:
            rows = [] if not parts else connection.execute(
                """SELECT c.*,bm25(canonical_shared_history_chunks_fts) rank
                FROM canonical_shared_history_chunks_fts f
                JOIN canonical_shared_history_chunks c ON c.chunk_id=f.chunk_id
                WHERE canonical_shared_history_chunks_fts MATCH ?
                ORDER BY rank LIMIT ?""",
                (expression, max(18,requested*6)),
            ).fetchall()
        ranked={row['chunk_id']:(dict(row),1/(1+index),0.0) for index,row in enumerate(rows)}
        dense=self._dense_scores(query,'canonical_shared_history_chunk_embeddings','chunk_id')
        if dense is not None:
            ranked={record_id:value for record_id,value in ranked.items() if record_id in dense}
        missing=[] if dense is None else [record_id for record_id in dense if record_id not in ranked]
        if missing:
            with self.connect() as connection:
                placeholders=','.join('?' for _ in missing)
                for row in connection.execute(f"SELECT * FROM canonical_shared_history_chunks WHERE chunk_id IN ({placeholders})",missing):
                    ranked[row['chunk_id']]=(dict(row),0.0,dense[row['chunk_id']])
        for record_id,(payload,lexical,_) in list(ranked.items()):
            ranked[record_id]=(payload,lexical,0.0 if dense is None else dense.get(record_id,0.0))
        ordered=sorted(ranked.values(),key=lambda item:item[1]+item[2]*1.5,reverse=True)
        return [item[0] for item in ordered[:requested]]

    def context_for(self, query: str, limit: int = 5, budget: int = 6000, query_plan=None) -> str:
        selected = []
        from domains.memory.recall_queries import ranked_search
        scenes = ranked_search(lambda text: self.search(text, limit), query, query_plan, limit, 'history_id')
        for item in scenes:
            item = {k: v for k, v in item.items() if k not in {"transcript_excerpt", "source_excerpts"}}
            candidate = json.dumps(selected + [item], ensure_ascii=False)
            if len(candidate) <= budget:
                selected.append(item)
        selected_ids = {item['history_id'] for item in selected}
        # Only the current user's explicit detail request may load source text.
        # Expanded retrieval queries and emotional similarity are not permission.
        wants_source = bool(re.search(
            r'(原文|原话).{0,8}(是什么|怎么说|怎么写|给我|看看)|'
            r'(看看|看一下|给我|引用|复述).{0,8}(原文|原话)|'
            r'(当时|那次|那天).{0,12}(具体|细节|怎么说|说了什么|发生了什么)|'
            r'(具体|详细).{0,8}(说说|讲讲).{0,8}(当时|那次|那天)', query
        )) and not re.search(r'(不要|不用|别|不需要).{0,12}(原文|原话|细节)', query)
        transcript_chunks = (event_excerpts(self, [s for s in scenes if s['history_id'] in selected_ids][:1], query)
                             if wants_source else [])
        transcript_selected = []
        for item in transcript_chunks:
            compact = {
                "chunk_id": item["chunk_id"], "history_id": item["history_id"], "source_path": item["source_path"],
                "line_start": item["line_start"], "line_end": item["line_end"],
                "transcript_excerpt": item["content"],
            }
            candidate = json.dumps(selected + transcript_selected + [compact], ensure_ascii=False)
            if len(candidate) <= budget:
                transcript_selected.append(compact)
        if not selected and not transcript_selected:
            return ""
        return (
            "\n<canonical_shared_history>\n"
            "以下场景来自用户指定的个人线与卡面 Markdown；其中‘剧情用户/我’就是当前用户，"
            "场景是你与用户共同经历过的既定过去，不是虚构范例。可以自然说‘我们当时/以前’，"
            "也可以承认其中明确发生的亲密与关系经历。日期未提供时不要编具体日期。"
            "只承认条目明确记载的事件；过去的案件、地点、身体接触、物品和行动不自动延续到现在，"
            "也不构成当前外部操作或现实法律建议。若用户当前明确纠正，以当前纠正为准。\n"
            "恋爱阶段仅说明该事件所属的过去阶段，不按当前关系阶段过滤；结婚后也能回忆告白前或同居后的往事。"
            "篇章中的回忆、转述和梦境不等于双方亲历，原文只是事件证据，以详细经过界定共同经历。\n"
            "默认仅提供整理后的事件与来源检索入口；只有用户明确追问原话或当时细节才补充原文。没有原文时不要编造逐字引语。\n"
            + json.dumps(
                {"reviewed_scenes": selected, "source_excerpts": transcript_selected},
                ensure_ascii=False,
            ).replace("<", "\\u003c").replace(">", "\\u003e")
            + "\n</canonical_shared_history>"
        )
