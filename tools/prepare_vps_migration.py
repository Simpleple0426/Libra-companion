"""Create a private, staged VPS migration bundle without resetting source data.

Run from the repository root. Only the new output directory is modified.
Database writers are briefly reserved together while SQLite backups are taken.
The generated life engine is provisioned but never ticked or enabled.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ('uploads', 'private_reading', 'room_media', 'music', 'xhs_runs')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)


def tables(path, exclude=()):
    result = {}
    with closing(readonly(path)) as db:
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if name in exclude:
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            h = hashlib.sha256()
            count = 0
            # Same physical snapshot: row order is unchanged by app_settings edits.
            for row in db.execute('SELECT * FROM ' + quoted):
                h.update(repr(row).encode('utf-8'))
                h.update(b'\n')
                count += 1
            result[name] = {'rows': count, 'sha256': h.hexdigest()}
    return result


def copy_stable(source, target):
    if source.is_symlink() or getattr(source, 'is_junction', lambda: False)():
        raise RuntimeError(f'Redirected file: {source}')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and digest(source) == digest(target):
        return
    before = source.stat()
    shutil.copy2(source, target)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f'Source changed during copy; retry in a quiet period: {source}')
    if digest(source) != digest(target):
        raise RuntimeError(f'Copy verification failed: {source}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-copy', action='store_true', help='Resume a failed copy before life initialization')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'releases') or (output.exists() and not args.resume_copy):
        parser.error('Output must be a NEW directory within releases/')
    if args.resume_copy and ((output / 'data' / 'life').exists() or (output / 'migration-report.json').exists()):
        parser.error('Cannot resume after life initialization')
    if output.exists():
        for p in output.rglob('*'):
            if p.is_symlink() or getattr(p, 'is_junction', lambda: False)() or not p.resolve().is_relative_to(output):
                parser.error('Cannot resume a redirected staging directory')
    source = ROOT / 'data'
    output.mkdir(parents=True, exist_ok=args.resume_copy)
    data = output / 'data'
    data.mkdir(exist_ok=args.resume_copy)
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'source_data_modified': False, 'stage': 'not_started',
              'reset_scope': 'life runtime, life memory, life inbox/outbox; retain chat and LMC'}
    databases = [source / n for n in ('libra.db', 'content.db', 'cognition.db')]
    databases += sorted(p for p in (source / 'music').rglob('*.db'))
    print('Taking coordinated SQLite snapshots...', flush=True)
    with closing(sqlite3.connect(databases[0], timeout=10)) as guard:
        for index, path in enumerate(databases[1:], 1):
            guard.execute(f'ATTACH DATABASE ? AS shard{index}', (str(path),))
        guard.execute('BEGIN IMMEDIATE')
        started = time.monotonic()
        try:
            def progress(status, remaining, total):
                if time.monotonic() - started > 90:
                    raise TimeoutError('Snapshot exceeded 90 seconds')
            for path in databases:
                dest = data / path.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with closing(readonly(path)) as src, closing(sqlite3.connect(dest)) as dst:
                    src.backup(dst, pages=1024, progress=progress)
        finally:
            guard.rollback()
    print('Snapshots complete; source write reservations released.', flush=True)
    for directory in MEDIA:
        root = source / directory
        for current, dirs, names in os.walk(root, followlinks=False):
            parent = Path(current)
            for name in dirs:
                p = parent / name
                if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
                    raise RuntimeError(f'Redirected directory: {p}')
            for name in names:
                p = parent / name
                if name.endswith(('.db', '.db-wal', '.db-shm', '.sqlite3', '.sqlite3-wal', '.sqlite3-shm')):
                    continue
                copy_stable(p, data / p.relative_to(source))
    print('Media copied and verified.', flush=True)

    core = data / 'libra.db'
    preserved_core = tables(core, ('app_settings',))
    unchanged = {str(p.relative_to(data)): digest(p) for p in data.rglob('*.db') if p != core}
    settings_backup = output / 'backups' / 'migrations' / 'pre-life-reset' / 'libra.db'
    settings_backup.parent.mkdir(parents=True, exist_ok=True)
    with closing(readonly(core)) as src, closing(sqlite3.connect(settings_backup)) as dst:
        src.backup(dst)
    with closing(sqlite3.connect(core)) as db:
        settings = dict(db.execute('SELECT key,value FROM app_settings'))
    policy = json.loads(settings['life_system_policy'])
    report['previous_proactive_enabled'] = settings.get('proactive_enabled', 'true')
    report['previous_life_mode'] = settings.get('life_system_mode')
    run_id = 'vps-fresh-life-v1'
    changed = {
        'life_system_mode': 'disabled', 'life_system_run_id': run_id,
        'proactive_enabled': 'false', 'local_life_proactive_cursor': '',
        'last_local_life_proactive_review': '', 'libra_life_timeline_cursor': '',
        'libra_last_processed_wake_event_id': '', 'libra_sleeping': 'false',
        'libra_sleep_started_at': '', 'libra_sleep_until': '',
        'daily_diary_pending': '', 'next_checkin_at': '',
        'mobile_app_foreground': 'false', 'mobile_app_foreground_at': '',
    }
    with closing(sqlite3.connect(core)) as db, db:
        for key, value in changed.items():
            db.execute('INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at', (key, value, datetime.now(timezone.utc).isoformat()))
    report['changed_setting_keys'] = sorted(changed)

    # Isolate imported path helpers before importing any project code.
    os.environ['LIBRA_CONFIG_DIR'] = str(output / 'isolated-config')
    os.environ['LIBRA_ENV_FILE'] = str(output / 'isolated-config' / '.env')
    os.environ['LIBRA_RUNTIME_DIR'] = str(data)
    os.environ['LIBRA_BACKUP_DIR'] = str(output / 'backups' / 'database')
    os.environ['LIBRA_LOG_DIR'] = str(output / 'logs')
    sys.path.insert(0, str(ROOT / 'backend'))
    from application.local_life import LifeModeControl, EnablePolicy
    def get_setting(key, default=''):
        with closing(sqlite3.connect(core)) as db:
            row = db.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
            return row[0] if row else default
    def set_setting(key, value):
        with closing(sqlite3.connect(core)) as db, db:
            db.execute('INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at', (key, value, datetime.now(timezone.utc).isoformat()))
    control = LifeModeControl(get_setting, set_setting, [core, data / 'content.db', data / 'cognition.db'], output / 'backups' / 'database')
    control.stage_configuration(run_id, EnablePolicy(**policy))
    report['life'] = control.provision(data / 'life', run_id, EnablePolicy(**policy))
    # The old backup ID points to a computer-local backup; do not use it on VPS.
    set_setting('life_system_backup_id', '')
    report['changed_setting_keys'] = sorted(set(report['changed_setting_keys']) | {'life_system_backup_id', 'life_system_audit'})
    assert tables(core, ('app_settings',)) == preserved_core, 'Non-settings core data changed'
    for name, before in unchanged.items():
        assert digest(data / name) == before, f'Preserved database changed: {name}'
    report['preserved_core_tables'] = preserved_core
    report['unchanged_database_sha256'] = unchanged
    with closing(readonly(data / 'cognition.db')) as db:
        report['preserved_memories'] = db.execute('SELECT COUNT(*) FROM lmc_memories').fetchone()[0]
        row = db.execute("SELECT value FROM memory_config WHERE key='main_thread_id'").fetchone()
        session = row[0] if row else None
    # Keep the exact current rollout separately. Installing it into the server's
    # model account and testing resume is a later deployment step.
    from dotenv import dotenv_values
    cfg = dotenv_values(ROOT / 'config' / '.env')
    cli_home = Path(cfg.get('LIBRA_CODEX_HOME') or Path.home() / '.codex')
    if session:
        matches = list((cli_home / 'sessions').rglob(f'*{session}*.jsonl'))
        if len(matches) != 1:
            raise RuntimeError('Expected exactly one current chat rollout; migration requires session review')
        copy_stable(matches[0], output / 'chat-session' / matches[0].relative_to(cli_home))
        report['chat_session'] = {'id': session, 'copied': True, 'server_resume_verified': False}
    print('Fresh life provisioned; all other database contents verified.', flush=True)
    checks = {}
    for p in list(data.rglob('*.db')) + list(data.rglob('*.sqlite3')):
        with closing(sqlite3.connect(p)) as db:
            checks[str(p.relative_to(data))] = db.execute('PRAGMA integrity_check').fetchone()[0]
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute('PRAGMA journal_mode=DELETE')
    if any(v != 'ok' for v in checks.values()):
        raise RuntimeError('Database integrity check failed')
    report['integrity'] = checks
    report['stage'] = 'verified_staged_life_disabled'
    report['pending'] = ['server chat-session install and resume check', 'server private service credentials', 'life activation and proactive restore after checks']
    (output / 'migration-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'README.txt').write_text(
        'PRIVATE MIGRATION PACKAGE\n\n'
        'Extract into a staging folder, not over a running deployment.\n'
        'Copy data/ to the EMPTY C:\\Libra\\data directory.\n'
        'Keep backups/ under C:\\Libra\\backups.\n'
        'Do not launch the backend yet: model session and service credentials remain to configure.\n'
        'Life is freshly provisioned but disabled; proactive contact is disabled for staging.\n'
        'chat-session/ contains the current private conversation rollout, not model authentication.\n'
        'The computer source data has NOT been reset. Later computer changes are not included.\n', encoding='utf-8')
    shutil.copy2(ROOT / 'tools' / 'verify_vps_migration.py', output / 'verify_vps_migration.py')
    files = sorted(p for p in output.rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm')))
    manifest = {p.relative_to(output).as_posix(): {'bytes': p.stat().st_size, 'sha256': digest(p)} for p in files}
    (output / 'checksums.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = output.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=5) as z:
        for p in files + [output / 'checksums.json']:
            z.write(p, p.relative_to(output))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('Archive CRC failed')
    print(json.dumps({'archive': str(archive), 'size_mb': round(archive.stat().st_size / 1048576, 1), 'files': len(files) + 1, 'messages': preserved_core['messages']['rows'], 'memories': report['preserved_memories'], 'integrity': checks}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
