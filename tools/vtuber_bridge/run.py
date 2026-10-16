"""Launch an isolated upstream checkout with the Libra Agent substituted."""
import argparse
import os
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vtuber-dir", type=Path, default=Path(__file__).resolve().parents[2] / "third_party" / "Open-LLM-VTuber")
    parser.add_argument("--libra-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    root = args.vtuber_dir.resolve()
    if not (root / "run_server.py").is_file():
        parser.error("Open-LLM-VTuber checkout not found")
    sys.path.insert(0, str(root))
    os.chdir(root)
    from src.open_llm_vtuber.agent.agent_factory import AgentFactory
    from agent import LibraAgent
    AgentFactory.create_agent = staticmethod(lambda *a, **kw: LibraAgent(args.libra_url))
    sys.argv = [str(root / "run_server.py")]
    runpy.run_path(str(root / "run_server.py"), run_name="__main__")


if __name__ == "__main__":
    main()
