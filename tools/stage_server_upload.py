"""Stage private Windows VPS files, preserving all runtime data and CLI sessions."""
from pathlib import Path
import argparse
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import socket
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
        '.dart_tool', '.gradle', '.kotlin', 'build', '.idea'}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--codex-home', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--finalize', action='store_true', help='Refresh metadata after staging-only exclusions')
    args = parser.parse_args()
    out = args.output.resolve()
    home = args.codex_home.resolve()
    if args.finalize:
        if out.parent != ROOT.parent or out == ROOT or not (out / 'migration-report.json').is_file():
            raise RuntimeError('Expected an existing sibling staging package')
        manifest = json.loads((out / 'checksums.json').read_text(encoding='utf-8'))
        for name in ('installed-libra.apk', 'installed-libra-base.apk'):
            key = 'project/data/' + name
            if not (out / key).exists():
                manifest.pop(key, None)
        for name in ('README.md', 'THIRD_PARTY_NOTICES.md', '.gitignore', '.editorconfig',
                     'tools/stage_server_upload.py'):
            target = out / 'project' / name
            if not target.resolve().is_relative_to(out):
                raise RuntimeError('Redirected package metadata')
            shutil.copy2(ROOT / name, target)
            manifest['project/' + name] = {'bytes': target.stat().st_size, 'sha256': digest(target)}
        for name, entry in manifest.items():
            target = out / name
            if not target.is_file() or target.stat().st_size != entry['bytes']:
                raise RuntimeError(f'Missing or resized staged file: {name}')
        (out / 'checksums.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        report = json.loads((out / 'migration-report.json').read_text(encoding='utf-8'))
        report['files'] = len(manifest)
        report['bytes'] = sum(v['bytes'] for v in manifest.values())
        (out / 'migration-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'total_gib': round(report['bytes'] / 1024**3, 2),
            'project_gib': round(sum(v['bytes'] for k, v in manifest.items() if k.startswith('project/')) / 1024**3, 2),
            'codex_gib': round(sum(v['bytes'] for k, v in manifest.items() if k.startswith('codex/')) / 1024**3, 2),
            'checked_databases': len(report['databases']), 'files': len(manifest),
            'auth_included': (out / 'codex' / 'auth.json').exists()}), flush=True)
        return
    if out.parent != ROOT.parent or (out.exists() and not args.resume) or out == ROOT:
        parser.error('Output must be a new sibling directory of the project')
    if not home.is_dir():
        parser.error('Codex home does not exist')
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1', 8000)) == 0:
            raise RuntimeError('Stop the local backend before staging')
    with closing(readonly(ROOT / 'data' / 'cognition.db')) as db:
        row = db.execute("SELECT value FROM memory_config WHERE key='main_thread_id'").fetchone()
        thread = row[0] if row else None
    if not thread or not list((home / 'sessions').rglob(f'*{thread}*.jsonl')):
        raise RuntimeError('Current main thread or its rollout is missing')
    if args.resume:
        staged_env = out / 'project' / 'config' / '.env'
        if not staged_env.is_file() or digest(staged_env) != digest(ROOT / 'config' / '.env'):
            raise RuntimeError('Resume requires the verified staging config from this project')
        for current, dirs, files in os.walk(out, followlinks=False):
            for name in dirs + files:
                p = Path(current) / name
                if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
                    raise RuntimeError(f'Redirected staging path: {p}')
    out.mkdir(exist_ok=args.resume)
    manifest = {}
    integrity = {}

    def copy_tree(src, dst, excludes=(), skip_names=()):
        jobs = []
        for current, dirs, names in os.walk(src, followlinks=False):
            parent = Path(current)
            dirs[:] = [d for d in dirs if d not in excludes]
            for d in dirs:
                p = parent / d
                if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
                    raise RuntimeError(f'Redirected directory: {p}')
            for name in names:
                p = parent / name
                if name in skip_names or name.endswith(('.pyc', '-wal', '-shm', '-journal')):
                    continue
                if p.is_symlink() or not p.resolve().is_relative_to(src.resolve()):
                    raise RuntimeError(f'Redirected file: {p}')
                jobs.append(p)

        def copy_file(p):
            target = dst / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            before = p.stat()
            key = target.relative_to(out).as_posix()
            if p.suffix in {'.db', '.sqlite', '.sqlite3'}:
                with closing(readonly(p)) as source, closing(sqlite3.connect(target)) as dest:
                    source.backup(dest, pages=1024)
                    result = [r[0] for r in dest.execute('PRAGMA integrity_check')]
                    if result != ['ok']:
                        raise RuntimeError(f'Invalid database: {target}: {result}')
                    integrity[key] = 'ok'
            else:
                source_hash = digest(p)
                if not target.is_file() or target.stat().st_size != before.st_size or digest(target) != source_hash:
                    shutil.copy2(p, target)
                after = p.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f'Source changed while copying: {p}')
                if source_hash != digest(target):
                    raise RuntimeError(f'Copy mismatch: {p}')
            return key, {'bytes': target.stat().st_size, 'sha256': digest(target)}

        with ThreadPoolExecutor(max_workers=8) as pool:
            for index, (key, entry) in enumerate(pool.map(copy_file, jobs), 1):
                manifest[key] = entry
                if index % 5000 == 0:
                    print(f'{src.name}: verified {index}/{len(jobs)} files', flush=True)
        print(f'Copied and verified {src.name}: {len(jobs)} files', flush=True)

    for directory in ('backend', 'libra', 'third_party', 'tools'):
        copy_tree(ROOT / directory, out / 'project' / directory, SKIP)
    copy_tree(ROOT / 'mobile' / 'assets', out / 'project' / 'mobile' / 'assets', SKIP)
    copy_tree(ROOT / 'config', out / 'project' / 'config')
    copy_tree(ROOT / 'data', out / 'project' / 'data',
              skip_names={'installed-libra.apk', 'installed-libra-base.apk'})
    copy_tree(home, out / 'codex', SKIP | {'cache', 'log', 'tmp', 'thread-writer-locks'},
              {'auth.json', 'installation_id', 'models_cache.json'})
    with closing(readonly(out / 'project' / 'data' / 'cognition.db')) as db:
        assert db.execute("SELECT value FROM memory_config WHERE key='main_thread_id'").fetchone()[0] == thread
    instructions = '''PRIVATE VPS UPLOAD - contains credentials and private conversations.

Copy project/ CONTENTS to C:\\Libra (C:\\Libra\\backend must exist).
Copy codex/ CONTENTS to C:\\LibraCodex; keep the VPS auth.json login.
Original source files and main thread were not reset or rewritten.
SQLite backups include WAL contents; old backups and APKs are not needed to run.
Do not start the backend yet: config/.env and CLI/MCP paths need server review.
Use LIBRA_CODEX_HOME=C:\\LibraCodex and the same account and CLI version.
Install Python dependencies and required npm services afresh on the server.
Backend stickers are included; mobile build tools and signing keys are omitted.
Public authentication and HTTPS are not yet configured; keep port 8000 private.
'''
    (out / 'UPLOAD-README.txt').write_text(instructions, encoding='utf-8')
    (out / 'checksums.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    report = {'main_thread_id': thread, 'databases': integrity, 'source_data_reset': False,
              'files': len(manifest), 'bytes': sum(v['bytes'] for v in manifest.values()),
              'server_resume_verified': False}
    (out / 'migration-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
