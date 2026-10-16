"""Command-line check for the independent Libra status reader."""

from __future__ import annotations

import argparse
import time

from libra_status import LibraStatusUnavailable, get_libra_status


def main() -> int:
    parser = argparse.ArgumentParser(description="读取左然的上班/法院/悠闲状态")
    parser.add_argument("base_url", help="例如 http://100.64.0.10:8000")
    parser.add_argument("--watch", action="store_true", help="持续轮询")
    parser.add_argument("--interval", type=float, default=30, help="轮询秒数，默认 30")
    args = parser.parse_args()

    while True:
        try:
            print(get_libra_status(args.base_url), flush=True)
        except LibraStatusUnavailable as error:
            print(f"暂时无法读取状态：{error}", flush=True)
            if not args.watch:
                return 1
        if not args.watch:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
