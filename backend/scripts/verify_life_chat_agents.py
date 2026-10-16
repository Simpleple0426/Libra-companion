"""Compatibility entrypoint for the versioned isolated life-agent evaluation.

The former script depended on a deleted fixture and an obsolete appointment
contract. See evals/README.md for scope, cases and reports.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from evals.run_life_eval import main as evaluate
    return evaluate()


if __name__ == '__main__':
    raise SystemExit(main())
