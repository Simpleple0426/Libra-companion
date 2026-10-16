"""Central filesystem layout for code, private runtime data and generated files."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent

def _path(name: str, default: Path) -> Path:
    value = Path(os.getenv(name) or default).expanduser()
    return (value if value.is_absolute() else PROJECT_ROOT / value).resolve()


# Bootstrap config first: consumers must never freeze paths before .env loads.
# Explicit process environment wins over the file, e.g. a VPS service config.
CONFIG_ROOT = _path('LIBRA_CONFIG_DIR', PROJECT_ROOT / 'config')
ENV_PATH = _path('LIBRA_ENV_FILE', CONFIG_ROOT / '.env')
load_dotenv(ENV_PATH, override=False)
RUNTIME_ROOT = _path('LIBRA_RUNTIME_DIR', PROJECT_ROOT / 'data')
LOG_ROOT = _path('LIBRA_LOG_DIR', PROJECT_ROOT / 'logs')
CACHE_ROOT = _path('LIBRA_CACHE_DIR', PROJECT_ROOT / 'cache')
BACKUP_ROOT = _path('LIBRA_BACKUP_DIR', PROJECT_ROOT / 'backups' / 'database')
DATABASE_PATH = RUNTIME_ROOT / 'libra.db'
CONTENT_DATABASE_PATH = RUNTIME_ROOT / 'content.db'
COGNITION_DATABASE_PATH = RUNTIME_ROOT / 'cognition.db'
UPLOAD_ROOT = RUNTIME_ROOT / 'uploads'
PRIVATE_READING_ROOT = RUNTIME_ROOT / 'private_reading'
ROOM_MEDIA_ROOT = RUNTIME_ROOT / 'room_media'
SECRETS_ROOT = CONFIG_ROOT / 'secrets'
MUSIC_CONFIG_ROOT = CONFIG_ROOT / 'music'
MUSIC_DATA_ROOT = RUNTIME_ROOT / 'music' / 'service'
MUSIC_DATABASE_PATH = RUNTIME_ROOT / 'music' / 'music.db'
XHS_RUN_ROOT = RUNTIME_ROOT / 'xhs_runs'

# A stale pre-migration deployment must fail rather than silently create an
# empty new database and make existing records appear lost.
if RUNTIME_ROOT != BACKEND_ROOT and (BACKEND_ROOT / 'libra.db').exists():
    raise RuntimeError('Legacy backend/libra.db still exists; migrate storage before starting')
_databases = (DATABASE_PATH, CONTENT_DATABASE_PATH, COGNITION_DATABASE_PATH)
if any(p.exists() for p in _databases) and not all(p.exists() for p in _databases):
    raise RuntimeError('Incomplete database set in LIBRA_RUNTIME_DIR; restore all three shards')
