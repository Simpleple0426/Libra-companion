"""Launch Uvicorn with direct log file handles instead of PowerShell pipes."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from infrastructure.paths import LOG_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--stdout", type=Path)
    parser.add_argument("--stderr", type=Path)
    parser.add_argument("--trace-imports", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    args.stdout = args.stdout or LOG_ROOT / f'backend-{stamp}.stdout.log'
    args.stderr = args.stderr or LOG_ROOT / f'backend-{stamp}.stderr.log'
    args.stdout.parent.mkdir(parents=True, exist_ok=True)
    args.stderr.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u"]
    if args.trace_imports:
        command += ["-X", "importtime"]
    command += ["-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(args.port),
                "--loop", "app.server_loop:create_loop"]
    with args.stdout.open("ab", buffering=0) as out, args.stderr.open("ab", buffering=0) as err:
        return subprocess.call(command, cwd=Path(__file__).resolve().parents[1], stdout=out, stderr=err)


if __name__ == "__main__":
    raise SystemExit(main())
