"""Fail CI when maintained text files are not UTF-8 or contain replacement text."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROOTS = (ROOT / 'backend', ROOT / 'mobile' / 'lib', ROOT / 'libra')
EXTENSIONS = {'.py', '.dart', '.json', '.jsonl', '.md', '.yaml', '.yml'}
IGNORED_PARTS = {'build', '.dart_tool', 'vendor', 'xhs_runs', '__pycache__'}


def problems() -> list[str]:
    found = []
    for source_root in ROOTS:
        for path in source_root.rglob('*'):
            if (not path.is_file() or path.suffix.lower() not in EXTENSIONS
                    or IGNORED_PARTS.intersection(path.parts)):
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError as error:
                found.append(f'{path.relative_to(ROOT)}: not UTF-8 ({error})')
                continue
            if '\ufffd' in text:
                found.append(f'{path.relative_to(ROOT)}: contains U+FFFD replacement characters')
    return found


if __name__ == '__main__':
    errors = problems()
    if errors:
        raise SystemExit('\n'.join(errors))
    print('UTF-8 source check passed')
