"""Prepare an isolated local test snapshot without changing migration sources."""
from pathlib import Path
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.test-local'
if TARGET.exists() and ('--resume' not in sys.argv or (TARGET / 'setup-report.json').exists()):
    raise SystemExit('Test directory already exists; refusing to overwrite it.')
TARGET.mkdir(exist_ok=True)
shutil.copytree(ROOT / 'config', TARGET / 'config', dirs_exist_ok=True)
database_files = []
def runtime_files():
    if '--finish' in sys.argv:
        return
    for directory, folders, files in os.walk(ROOT / 'data'):
        folders[:] = [name for name in folders if name not in {'migration-backups', 'cli-operations', 'xhs_runs'}]
        for name in files:
            yield Path(directory) / name

for source in runtime_files():
    if not source.is_file():
        continue
    if {'migration-backups', 'cli-operations'}.intersection(source.parts) or source.suffix in {'.apk', '.log'}:
        continue
    if source.name.endswith(('-wal', '-shm', '-journal')):
        continue
    destination = TARGET / 'data' / source.relative_to(ROOT / 'data')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as handle:
        is_database = handle.read(16) == b'SQLite format 3\x00'
    if is_database:
        print('Snapshot: ' + str(source.relative_to(ROOT)), flush=True)
        if '--resume' in sys.argv and destination.exists() and destination.stat().st_size == source.stat().st_size:
            with closing(sqlite3.connect(destination)) as completed:
                if completed.execute('PRAGMA quick_check').fetchone()[0] == 'ok':
                    database_files.append(destination)
                    continue
        started = time.monotonic()
        def progress(status, remaining, total):
            if time.monotonic() - started > 90:
                raise RuntimeError('Database snapshot timeout: ' + str(source.relative_to(ROOT)))
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(destination)) as snapshot:
                original.backup(snapshot, progress=progress)
                assert snapshot.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        database_files.append(destination)
    elif not destination.exists() or destination.stat().st_size != source.stat().st_size:
        shutil.copy2(source, destination)
print('Snapshot copied and databases checked.', flush=True)

profile = TARGET / 'codex'
profile.mkdir(exist_ok=True)
values = dotenv_values(ROOT / 'config' / '.env')
old_profile = Path(values.get('LIBRA_CODEX_HOME') or Path.home() / '.codex-libra')
if not (profile / 'auth.json').exists():
    shutil.copy2(old_profile / 'auth.json', profile / 'auth.json')
env_file = TARGET / 'config' / '.env'
for key, value in {
    'LIBRA_CONFIG_DIR': TARGET / 'config',
    'LIBRA_ENV_FILE': env_file,
    'LIBRA_RUNTIME_DIR': TARGET / 'data',
    'LIBRA_LOG_DIR': TARGET / 'logs',
    'LIBRA_CACHE_DIR': ROOT / 'cache',
    'LIBRA_BACKUP_DIR': TARGET / 'backups',
    'LIBRA_CODEX_HOME': profile,
}.items():
    set_key(str(env_file), key, str(value))

command = [shutil.which('codex.cmd') or shutil.which('codex'), 'exec', '--json', '--skip-git-repo-check']
if values.get('LIBRA_LLM_MODEL'):
    command += ['--model', values['LIBRA_LLM_MODEL']]
command += ['这是 Libra 本地测试专用的新线程。请只回复“测试线程已建立”，不要调用工具。']
result = subprocess.run(command, cwd=ROOT / 'backend',
    env={**os.environ, 'CODEX_HOME': str(profile)}, capture_output=True, text=True,
    encoding='utf-8', timeout=180)
events = []
for line in result.stdout.splitlines():
    try:
        events.append(json.loads(line))
    except ValueError:
        pass
thread = next((e.get('thread_id') for e in events if e.get('type') == 'thread.started'), None)
if result.returncode or not thread or not any(e.get('type') == 'turn.completed' for e in events):
    raise SystemExit('New thread creation failed; test backend has not been started. Inspect CLI authentication/model availability.')
with sqlite3.connect(TARGET / 'data' / 'cognition.db') as db:
    db.execute("DELETE FROM memory_config WHERE key IN ('main_thread_id','previous_main_thread_id','start_fresh_thread','daily_thread_handoff')")
    db.execute("INSERT INTO memory_config (key,value) VALUES ('main_thread_id',?)", (thread,))
with sqlite3.connect(TARGET / 'data' / 'libra.db') as db:
    db.execute('DELETE FROM push_tokens')
(TARGET / 'setup-report.json').write_text(json.dumps({'test_thread': thread,
    'source_data_changed': False, 'sqlite_snapshots': len(database_files)}, indent=2), encoding='utf-8')
print('TEST_THREAD=' + thread, flush=True)
