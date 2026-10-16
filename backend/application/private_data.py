"""Versioned private-data ZIP export and restore for Libra Companion."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from scripts.retire_legacy_data import RETIRED_SETTING_KEYS
from application.turn_pipeline import TABLES as TURN_TABLES


FORMAT_NAME = "libra-private-data"
FORMAT_VERSION = 12
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ENTRY_COUNT = 10_000

BASE_EXPORT_TABLES = (
    "app_settings",
    "messages",
    "favorite_messages",
    "call_sessions",
    "call_turns",
    "letters",
    "shared_moments",
    "shared_moment_comments",
    "user_timeline_events",
    "calendar_events",
    "todos",
    "habits",
    "habit_checkins",
    "focus_sessions",
)

# Evidence and audits are portable; thread pointers and rebuildable search caches are not.
SOURCE_MEMORY_TABLES = ('raw_experiences', 'experience_segments', 'segment_experiences', 'memory_jobs', 'cognitive_traces')
NATIVE_LMC_TABLES = (
    'lmc_memories', 'lmc_event_context', 'lmc_sources', 'lmc_revisions',
    'lmc_usage_events', 'lmc_recall_logs', 'lmc_memory_coordinates',
    'lmc_memory_relations', 'lmc_relation_jobs', 'lmc_extraction_decisions', 'lmc_memory_audits',
    'lmc_dream_pages', 'lmc_dream_usage',
    'lmc_dream_entries',
)
MEMORY_TABLES = SOURCE_MEMORY_TABLES + NATIVE_LMC_TABLES
AFFECT_TABLES = ('affect_events','affect_state','affect_observations')
EXPORT_TABLES = BASE_EXPORT_TABLES + MEMORY_TABLES + AFFECT_TABLES + TURN_TABLES

# These values are runtime/device bookkeeping and must not be restored as
# personal configuration. API keys live in .env and never enter the archive.
APP_SETTING_EXCLUDE = {
    "device_context_enabled",
    "invalid_codex_thread_id",
    "mobile_app_foreground",
    "mobile_app_foreground_at",
    "next_checkin_at",
    *RETIRED_SETTING_KEYS,
}

DELETE_ORDER = tuple(reversed(TURN_TABLES)) + tuple(reversed(AFFECT_TABLES)) + tuple(reversed(MEMORY_TABLES)) + (
    "favorite_messages",
    "shared_moment_comments",
    "call_turns",
    "habit_checkins",
    "shared_moments",
    "call_sessions",
    "letters",
    "messages",
    "libra_attribute_adjustments",
    "libra_attribute_snapshots",
    "libra_state_events",
    "libra_timeline_events",
    "user_timeline_events",
    "calendar_events",
    "todos",
    "habits",
    "focus_sessions",
)


class PrivateDataError(ValueError):
    pass


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _connect(database_path: Path) -> sqlite3.Connection:
    from infrastructure.sqlite.connection import connect
    return connect(database_path, timeout=30)


def _rows(connection: sqlite3.Connection, table: str) -> list[dict]:
    schema = _table_schema(connection, table)
    if table in MEMORY_TABLES + AFFECT_TABLES + TURN_TABLES and not connection.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return []
    if table == "app_settings":
        placeholders = ",".join("?" for _ in APP_SETTING_EXCLUDE)
        query = (
            f'SELECT * FROM app_settings WHERE key NOT IN ({placeholders}) '
            "ORDER BY key"
        )
        values = connection.execute(query, tuple(sorted(APP_SETTING_EXCLUDE))).fetchall()
    else:
        values = connection.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
    return [dict(row) for row in values if table!='app_settings' or not str(row['key']).startswith('libra_schedule_')]


def _media_files(database: dict[str, list[dict]], upload_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for row in database.get('cognition_turns', []):
        result = json.loads(row.get('response_json') or 'null')
        if isinstance(result, dict) and str(result.get('media_url', '')).startswith('/uploads/chat/'):
            filename = Path(result['media_url']).name
            source = upload_dir / filename
            if source.is_file():
                files['media/chat/' + filename] = source
    for table in ("messages", "shared_moments"):
        for row in database.get(table, []):
            media_url = str(row.get("media_url") or "")
            prefix = "/uploads/chat/"
            if not media_url.startswith(prefix):
                continue
            filename = Path(media_url.removeprefix(prefix)).name
            if not filename:
                continue
            source = upload_dir / filename
            if source.is_file():
                files[f"media/chat/{filename}"] = source
    return files


def export_private_data(database_path: Path, upload_dir: Path) -> tuple[bytes, dict]:
    connection = _connect(database_path)
    try:
        connection.execute("BEGIN")
        database = {table: _rows(connection, table) for table in EXPORT_TABLES}
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()

    database_bytes = _json_bytes({"tables": database})
    media = _media_files(database, upload_dir)
    manifest = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "database_schema_version": schema_version,
        "exported_at": datetime.now().astimezone().isoformat(),
        "tables": {name: len(database[name]) for name in EXPORT_TABLES},
        "database_sha256": _sha256(database_bytes),
        "media": {},
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("database.json", database_bytes)
        for archive_name, source in sorted(media.items()):
            content = source.read_bytes()
            manifest["media"][archive_name] = {
                "size": len(content),
                "sha256": _sha256(content),
            }
            archive.writestr(archive_name, content)
        archive.writestr("manifest.json", _json_bytes(manifest))
    return buffer.getvalue(), manifest


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _read_archive(content: bytes) -> tuple[dict, dict, dict[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise PrivateDataError("文件不是有效的 Libra ZIP 数据包") from error
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRY_COUNT:
            raise PrivateDataError("ZIP 文件条目过多")
        if any(not _safe_member(info.filename) for info in infos):
            raise PrivateDataError("ZIP 中包含不安全的文件路径")
        if sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES:
            raise PrivateDataError("解压后的数据超过 512MB 限制")
        names = {info.filename for info in infos}
        if not {"manifest.json", "database.json"}.issubset(names):
            raise PrivateDataError("ZIP 缺少 manifest.json 或 database.json")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            database_bytes = archive.read("database.json")
            database = json.loads(database_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PrivateDataError("数据包 JSON 无法解析") from error
        if manifest.get("format") != FORMAT_NAME:
            raise PrivateDataError("不是 Libra 私人数据包")
        version = manifest.get("version")
        if not isinstance(version, int) or version < 10 or version > FORMAT_VERSION:
            raise PrivateDataError(f"不支持的数据包版本：{version}；仅支持 LMC 原生备份（v10及以后），旧包需先用旧版本升级导出")
        if manifest.get("database_sha256") != _sha256(database_bytes):
            raise PrivateDataError("database.json 校验失败，文件可能已损坏")
        tables = database.get("tables") if isinstance(database, dict) else None
        if not isinstance(tables, dict):
            raise PrivateDataError("database.json 缺少 tables")
        if version <= 11:
            tables.setdefault('lmc_dream_entries', [])
        if version == 10:
            for table in ('lmc_dream_pages', 'lmc_dream_usage'):
                tables.setdefault(table, [])
        missing = [table for table in EXPORT_TABLES if table not in tables]
        if missing:
            raise PrivateDataError("数据包缺少表：" + "、".join(missing))
        media: dict[str, bytes] = {}
        media_manifest = manifest.get("media", {})
        if not isinstance(media_manifest, dict):
            raise PrivateDataError("媒体清单格式不正确")
        for name, metadata in media_manifest.items():
            if not isinstance(name, str) or not name.startswith("media/chat/"):
                raise PrivateDataError("媒体路径不正确")
            if name not in names or not isinstance(metadata, dict):
                raise PrivateDataError(f"媒体文件缺失：{name}")
            item = archive.read(name)
            if metadata.get("size") != len(item) or metadata.get("sha256") != _sha256(item):
                raise PrivateDataError(f"媒体文件校验失败：{name}")
            media[name] = item
        return manifest, tables, media


def _table_schema(connection, table):
    from infrastructure.sqlite.connection import COGNITION_TABLES, CONTENT_TABLES
    if table not in EXPORT_TABLES:
        raise PrivateDataError('unknown_export_table')
    domain = 'cognition' if table in COGNITION_TABLES else 'content' if table in CONTENT_TABLES else 'core'
    return connection.route_schemas.get(domain, 'main')


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    schema = _table_schema(connection, table)
    return [str(row[1]) for row in connection.execute(f'PRAGMA {schema}.table_info({table})')]


def _validate_rows(
    connection: sqlite3.Connection, table: str, value: object
) -> tuple[list[str], list[dict]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise PrivateDataError(f"表 {table} 的数据格式不正确")
    if table=='app_settings':
        value=[row for row in value if not str(row.get('key','')).startswith('libra_schedule_')]
    available = _table_columns(connection, table)
    if not available:
        raise PrivateDataError(f"当前数据库缺少表：{table}")
    unknown = sorted({key for row in value for key in row if key not in available})
    if unknown:
        raise PrivateDataError(f"表 {table} 包含未知字段：{'、'.join(unknown)}")
    columns = [column for column in available if any(column in row for row in value)]
    return columns, value


def import_private_data(
    content: bytes, database_path: Path, upload_dir: Path
) -> dict:
    manifest, tables, media = _read_archive(content)
    if not isinstance(tables['app_settings'], list) or any(not isinstance(row, dict) for row in tables['app_settings']):
        raise PrivateDataError('app_settings 数据格式不正确')
    tables['app_settings'] = [row for row in tables['app_settings'] if row.get('key') not in RETIRED_SETTING_KEYS]
    from domains.memory.store import MemoryStore, utc
    memory_store = MemoryStore(database_path)
    memory_store.initialize()
    from domains.affect.service import AffectService
    AffectService(memory_store).initialize()
    from application.turn_pipeline import TurnPipeline
    TurnPipeline(memory_store).initialize()
    connection = _connect(database_path)
    try:
        validated = {
            table: _validate_rows(connection, table, tables[table])
            for table in EXPORT_TABLES
        }
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            if memory_store.fts_available:
                connection.execute("DELETE FROM lmc_fts")
            connection.execute("DELETE FROM lmc_search_documents")
            connection.execute("DELETE FROM lmc_embeddings")
            connection.execute("DELETE FROM lmc_session_recall")
            connection.execute("DELETE FROM lmc_calendar_sources")
            connection.execute("DELETE FROM lmc_calendar_summaries")
            connection.execute("DELETE FROM lmc_dream_jobs")
            connection.execute("DELETE FROM memory_config WHERE key='dream_requested'")
            connection.execute("DELETE FROM memory_config WHERE key='calendar_summary_signature'")
            # Local queue cutoffs refer to SQLite rowids, not portable source IDs.
            connection.execute("DELETE FROM memory_stream_boundaries")
            # 导入会重新分配原始记录的位置，旧处理进度不能沿用。
            connection.execute("DELETE FROM memory_config WHERE key LIKE 'segment_progress:%'")
            for table in DELETE_ORDER:
                connection.execute(f'DELETE FROM {table}')
            imported_setting_keys = [
                row.get("key") for row in tables["app_settings"] if row.get("key")
            ]
            for key in imported_setting_keys:
                connection.execute("DELETE FROM app_settings WHERE key = ?", (key,))
            for table in EXPORT_TABLES:
                columns, rows = validated[table]
                if not rows:
                    continue
                if not columns:
                    raise PrivateDataError(f"表 {table} 没有可导入字段")
                quoted = ",".join(f'"{column}"' for column in columns)
                placeholders = ",".join("?" for _ in columns)
                values = [tuple(row.get(column) for column in columns) for row in rows]
                connection.executemany(
                    f'INSERT INTO {table} ({quoted}) VALUES ({placeholders})', values
                )
            connection.execute("UPDATE lmc_relation_jobs SET status='retryable',lease_token=NULL,lease_until=NULL,next_attempt_at=? WHERE status='processing'", (utc(),))
            # An in-flight worker from the exporting process cannot own a restored lease.
            connection.execute("UPDATE memory_jobs SET job_status='retryable',lease_token=NULL,lease_until=NULL,next_attempt_at=? WHERE job_status='processing'", (utc(),))
            connection.execute("UPDATE affect_events SET status='pending',lease_token=NULL,lease_until=NULL WHERE status='processing'")
            from domains.affect.engine import initial
            connection.execute('INSERT OR IGNORE INTO affect_state VALUES (1,0,?)',(json.dumps(initial()),))
            connection.execute("UPDATE memory_jobs SET job_kind='lmc' WHERE job_kind='episode'")
            connection.execute("UPDATE memory_jobs SET job_status='failed',error_code='feature_removed',lease_token=NULL,lease_until=NULL WHERE job_kind!='lmc' AND job_status IN ('pending','processing','retryable')")
            schemas = set(connection.route_schemas.values()) or {'main'}
            violations = [row for schema in schemas
                          for row in connection.execute(f'PRAGMA {schema}.foreign_key_check')]
            if any(row[0] in MEMORY_TABLES + AFFECT_TABLES + TURN_TABLES for row in violations):
                raise PrivateDataError("记忆证据关联不完整，已取消导入")
            for row in connection.execute('''SELECT m.memory_id,m.revision,m.title,m.content,COALESCE(e.topics_json,'[]') AS topics_json
                FROM lmc_memories m LEFT JOIN lmc_event_context e USING(memory_id)''').fetchall():
                memory_store._index(connection,row['memory_id'],row['revision'],row['title']+' '+row['content']+' '+' '.join(json.loads(row['topics_json'])))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    except sqlite3.Error as error:
        raise PrivateDataError(f"数据库导入失败：{error}") from error
    finally:
        connection.close()

    from domains.memory.lmc import initialize as initialize_lmc
    initialize_lmc(memory_store)
    upload_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="libra-import-") as temporary:
        staging = Path(temporary)
        for archive_name, item in media.items():
            filename = PurePosixPath(archive_name).name
            target = staging / filename
            target.write_bytes(item)
        for source in staging.iterdir():
            shutil.copy2(source, upload_dir / source.name)

    return {
        "version": manifest["version"],
        "exported_at": manifest.get("exported_at"),
        "tables": {table: len(tables[table]) for table in EXPORT_TABLES},
        "media_files": len(media),
        "personalization": {
            row["key"]: row.get("value")
            for row in tables["app_settings"]
            if row.get("key")
            in {
                "libra_name",
                "user_name",
                "libra_nickname",
                "user_nickname",
                "user_address",
                "met_at",
                "checkin_min_minutes",
                "checkin_max_minutes",
                "proactive_enabled",
                "weather_reminder_enabled",
                "state_update_enabled",
                "emotion_impulse_enabled",
            }
        },
    }
