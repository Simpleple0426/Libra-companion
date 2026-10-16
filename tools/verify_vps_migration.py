"""Verify a staged migration package without importing or starting the backend."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent).resolve()
    manifest = json.loads((root / 'checksums.json').read_text(encoding='utf-8'))
    for name, expected in manifest.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError(f'Missing or redirected file: {name}')
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                h.update(block)
        if path.stat().st_size != expected['bytes'] or h.hexdigest() != expected['sha256']:
            raise RuntimeError(f'File verification failed: {name}')
    report = json.loads((root / 'migration-report.json').read_text(encoding='utf-8'))
    if report['stage'] != 'verified_staged_life_disabled':
        raise RuntimeError('Package is not a verified staged migration')
    print(f'OK: {len(manifest)} files verified. Backend was not started.')


if __name__ == '__main__':
    main()
