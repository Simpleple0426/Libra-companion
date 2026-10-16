"""Prepare a paired or credential-free client zip without printing credentials."""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from infrastructure.paths import SECRETS_ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend')
    parser.add_argument('--unpaired', action='store_true', help='Build without private addresses or tokens')
    args = parser.parse_args()
    from server import valid_backend
    if args.unpaired:
        if args.backend:
            parser.error('--unpaired cannot be combined with --backend')
        address, token = '', ''
    else:
        if not args.backend:
            parser.error('--backend is required unless --unpaired is used')
        address = valid_backend(args.backend)
        SECRETS_ROOT.mkdir(parents=True, exist_ok=True)
        token_file = SECRETS_ROOT / 'watch_together.token'
        if not token_file.exists():
            token_file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        token = token_file.read_text(encoding='utf-8').strip()
    folder = ROOT / 'releases' / 'watch-together-windows'
    folder.mkdir(parents=True, exist_ok=True)
    client_files = ('server.py', 'index.html', 'start.cmd', 'README.md', 'subtitles.py', 'timeline.js', 'app.js')
    for name in client_files:
        shutil.copy2(Path(__file__).parent / name, folder / name)
    (folder / 'connection.json').write_text(json.dumps({
        'backend': address, 'token': token}, ensure_ascii=False), encoding='utf-8')
    archive = ROOT / 'releases' / 'watch-together-windows.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in (*client_files, 'connection.json'):
            bundle.write(folder / name, folder.name + '/' + name)
    print(archive)


if __name__ == '__main__':
    main()
