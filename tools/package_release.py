"""Create a source release without local runtime data or credentials."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ('backend', 'mobile', 'libra', 'tools', 'docs', 'third_party')
ROOT_FILES = ('README.md', 'THIRD_PARTY_NOTICES.md', '.gitignore', '.editorconfig')
EXCLUDED_DIRS = {'.git', '__pycache__', '.pytest_cache', '.dart_tool', '.gradle', '.kotlin',
                 '.idea', 'node_modules', 'build', 'dist', 'data', 'secrets', 'uploads',
                 'private_reading', 'room_media', 'backups', 'logs', 'xhs_runs'}
EXCLUDED_FILES = {'local.properties', 'key.properties', 'google-services.json',
                  '.flutter-plugins-dependencies', '.secret', '.netease_cred', 'netease_session.cookie'}


def excluded_file(path: Path) -> bool:
    name = path.name.lower()
    return (name in EXCLUDED_FILES or (name.startswith('.env') and name != '.env.example')
            or any(name.endswith(s) for s in ('.db', '.db-wal', '.db-shm', '.sqlite3', '.sqlite3-wal',
                                             '.sqlite3-shm', '.pyc', '.log', '.jks', '.keystore', '.pem', '.apk', '.zip')))


def release_files():
    for name in ROOT_FILES:
        if (ROOT / name).is_file():
            yield ROOT / name
    for directory in SOURCE_DIRS:
        for current, dirs, files in os.walk(ROOT / directory, followlinks=False):
            parent = Path(current)
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS
                       and not (parent == ROOT / 'backend' and d in {'life', 'runtime'})
                       and not (parent / d).is_symlink()
                       and not getattr(parent / d, 'is_junction', lambda: False)()]
            for name in files:
                p = parent / name
                if p.is_symlink() or not p.resolve().is_relative_to(ROOT):
                    raise RuntimeError(f'Redirected source path: {p}')
                if not excluded_file(p):
                    yield p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / 'releases' / f'libra-source-{datetime.now():%Y%m%d-%H%M%S}.zip').resolve()
    if output.exists():
        parser.error('Output already exists; choose a new filename')
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(release_files())
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p, p.relative_to(ROOT).as_posix())
    print(f'{len(files)} source files packaged: {output}')


if __name__ == '__main__':
    main()
