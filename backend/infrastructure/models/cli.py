"""CLI adapters for Libra's conversational model providers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class CliResult:
    text: str | None
    session_id: str | None
    usage: dict[str, int] | None = None
    searched_web: bool = False


def provider_name() -> str:
    value = os.environ.get("LIBRA_LLM_PROVIDER", "codex").strip().lower()
    if value not in {"codex", "claude"}:
        raise RuntimeError(
            "LIBRA_LLM_PROVIDER 只能填写 codex 或 claude"
        )
    return value


def model_name() -> str:
    return os.environ.get("LIBRA_LLM_MODEL", "").strip()


@lru_cache(maxsize=32)
def codex_session_available(session_id: str | None) -> bool:
    """Check that a persisted Codex pointer still has a local rollout file."""
    if not session_id:
        return False
    configured = os.environ.get("LIBRA_CODEX_HOME", "").strip()
    root = (Path(configured).expanduser() if configured else Path.home() / '.codex') / 'sessions'
    if not root.exists():
        return False
    return next(root.rglob(f'*{session_id}*.jsonl'), None) is not None


def _resolve_command(provider: str) -> str:
    override = os.environ.get(
        "LIBRA_CODEX_COMMAND" if provider == "codex" else "LIBRA_CLAUDE_COMMAND",
        "",
    ).strip()
    if override:
        return override

    names = ("codex.cmd", "codex") if provider == "codex" else ("claude.cmd", "claude")
    for name in names:
        discovered = shutil.which(name)
        if discovered:
            return discovered

    windows_default = Path.home() / "AppData" / "Roaming" / "npm" / names[0]
    if windows_default.exists():
        return str(windows_default)
    return names[0]


def _environment(provider: str) -> dict[str, str]:
    environment = os.environ.copy()
    node_directories = [Path("C:/Program Files/nodejs"), Path("E:/Libra/node-v22.22.3-win-x64")]
    available = [str(path) for path in node_directories if path.exists()]
    if available:
        environment["PATH"] = os.pathsep.join(available + [environment.get("PATH", "")])

    if provider == "codex":
        # Do not leak internal variables from a parent Codex process.
        for name in list(environment):
            if name.startswith("CODEX_") and name != "CODEX_HOME":
                environment.pop(name, None)
        home = os.environ.get("LIBRA_CODEX_HOME", "").strip()
        if home:
            environment["CODEX_HOME"] = str(Path(home).expanduser())
    else:
        # Claude Code refuses nested launches when this marker leaks from a parent.
        environment.pop("CLAUDECODE", None)
        config_dir = os.environ.get("LIBRA_CLAUDE_CONFIG_DIR", "").strip()
        if config_dir:
            environment["CLAUDE_CONFIG_DIR"] = str(Path(config_dir).expanduser())
    return environment


def _codex_command(
    prompt: str, session_id: str | None, image_paths: list[Path], selected_model: str | None = None
) -> tuple[list[str], str]:
    # VPS deployments may intentionally omit .git; retain the same session
    # while allowing execution from the deployed application directory.
    command = [_resolve_command("codex"), "exec", "--json", "--skip-git-repo-check"]
    selected_model = (selected_model or model_name()).strip()
    if selected_model:
        command.extend(["--model", selected_model])
    if session_id:
        command[2:2] = ["resume", session_id]
    for image_path in image_paths:
        command.extend(["--image", str(image_path.resolve())])
    return command, prompt


def _claude_command(
    prompt: str, session_id: str | None, image_paths: list[Path], selected_model: str | None = None
) -> tuple[list[str], str]:
    command = [
        _resolve_command("claude"),
        "--print",
        "--output-format",
        "json",
        "--disallowedTools",
        "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Task",
    ]
    selected_model = (selected_model or model_name()).strip()
    if selected_model:
        command.extend(["--model", selected_model])
    if session_id:
        command.extend(["--resume", session_id])
    if image_paths:
        paths = "\n".join(f"- {path.resolve()}" for path in image_paths)
        prompt = (
            f"{prompt}\n\n<attached_images>\n{paths}\n</attached_images>\n"
            "请使用 Read 工具查看上述图片后再回答。"
        )
        command.extend(["--allowedTools", "Read"])
    return command, prompt


def _parse_codex(stdout: str, previous_session_id: str | None) -> CliResult:
    reply = None
    session_id = previous_session_id
    usage = None
    searched_web = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            session_id = event.get("thread_id") or session_id
        elif event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "web_search":
                searched_web = True
            if item.get("type") == "agent_message":
                reply = item.get("text")
        elif event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            raw = event["usage"]
            parsed_usage = {
                "input_tokens": int(raw.get("input_tokens") or 0),
                "cached_input_tokens": int(raw.get("cached_input_tokens") or 0),
                "output_tokens": int(raw.get("output_tokens") or 0),
                "reasoning_output_tokens": int(raw.get("reasoning_output_tokens") or 0),
                "total_tokens": int(raw.get("total_tokens") or 0),
            }
            # Ignore impossible provider counters without discarding the reply.
            max_input = int(os.environ.get("LIBRA_MAX_RECORDED_INPUT_TOKENS", "2000000"))
            max_output = int(os.environ.get("LIBRA_MAX_RECORDED_OUTPUT_TOKENS", "200000"))
            if (0 <= parsed_usage["input_tokens"] <= max_input
                    and 0 <= parsed_usage["cached_input_tokens"] <= parsed_usage["input_tokens"]
                    and 0 <= parsed_usage["output_tokens"] <= max_output
                    and 0 <= parsed_usage["reasoning_output_tokens"] <= max_output
                    and 0 <= parsed_usage["total_tokens"] <= max_input + max_output):
                usage = parsed_usage
    return CliResult(reply, session_id, usage, searched_web)


def _parse_claude(stdout: str, previous_session_id: str | None) -> CliResult:
    try:
        payload = json.loads(stdout.strip())
    except json.JSONDecodeError as error:
        raise RuntimeError("Claude Code 返回了无法解析的 JSON") from error
    if payload.get("is_error") or payload.get("subtype") not in {None, "success"}:
        raise RuntimeError(str(payload.get("result") or "Claude Code execution failed"))
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    return CliResult(payload.get("result"), payload.get("session_id") or previous_session_id, usage)


def _stop_cli_process(process):
    """Only clean up the process tree launched for this particular invocation."""
    try:
        process.wait(timeout=.15)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _run_codex_stream(command, prompt, session_id, timeout):
    """Accept a complete JSONL turn without waiting for launcher pipe teardown."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=_environment('codex'),
                               cwd=Path(__file__).resolve().parents[2])
    output = queue.Queue()
    errors = deque(maxlen=64)
    def read_output():
        try:
            for line in process.stdout:
                output.put(line)
        finally:
            process.stdout.close()
            output.put(None)
    def read_errors():
        try:
            while True:
                chunk = process.stderr.read(4096)
                if not chunk:
                    break
                errors.append(chunk)
        finally:
            process.stderr.close()
    def write_input():
        try:
            process.stdin.write(prompt.encode('utf-8'))
            process.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
    workers = [threading.Thread(target=fn, daemon=True) for fn in (read_output, read_errors, write_input)]
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + timeout
    events = []
    try:
        while True:
            try:
                # Drain already-read records even at the deadline. A partial
                # agent message alone is never treated as a completed turn.
                line = output.get(timeout=max(0, deadline-time.monotonic()))
            except queue.Empty:
                raise subprocess.TimeoutExpired(command, timeout)
            if line is None:
                error = b''.join(errors).decode('utf-8', errors='replace').strip()
                raise RuntimeError(error or 'Codex 未返回完整回合结果')
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if event.get('type') in {'thread.started', 'item.completed', 'turn.completed'}:
                events.append(json.dumps(event, ensure_ascii=False))
            if event.get('type') == 'turn.failed':
                raise RuntimeError(str(event.get('error') or 'Codex 回合失败'))
            if event.get('type') == 'turn.completed':
                result = _parse_codex('\n'.join(events), session_id)
                if not isinstance(result.text, str) or not result.text.strip():
                    raise RuntimeError('Codex 完成回合但没有返回回复')
                return result
    finally:
        _stop_cli_process(process)
        for worker in workers:
            worker.join(timeout=.2)


def run_cli(
    prompt: str,
    session_id: str | None = None,
    image_paths: list[Path] | None = None,
    timeout: int = 120,
    model: str | None = None,
    web_search: bool = False,
) -> CliResult:
    from application.tool_execution import remaining_timeout
    timeout = remaining_timeout(timeout)
    provider = provider_name()
    paths = image_paths or []
    command, stdin_prompt = (
        _codex_command(prompt, session_id, paths, model)
        if provider == "codex"
        else _claude_command(prompt, session_id, paths, model)
    )
    if web_search:
        if provider != 'codex':
            raise RuntimeError('当前模型通道不支持电影资料检索')
        command.extend(['-c', 'web_search="live"'])
    try:
        if provider == 'codex':
            return _run_codex_stream(command, stdin_prompt, session_id, timeout)
        result = subprocess.run(
            command,
            input=stdin_prompt.encode("utf-8"),
            capture_output=True,
            env=_environment(provider),
            cwd=Path(__file__).resolve().parents[2],
            timeout=timeout,
        )
    except FileNotFoundError as error:
        cli_name = "Codex CLI" if provider == "codex" else "Claude Code CLI"
        raise RuntimeError(f"找不到 {cli_name}，请先安装并登录") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{provider} 回复超时，请稍后重试") from error
    # Codex/Claude JSON is UTF-8, while Windows launcher errors can be emitted
    # using the active ANSI code page.  Capture bytes and decode defensively so
    # a localized CLI error never crashes the ASGI request handler.
    stdout = (result.stdout or b"").decode("utf-8", errors="replace")
    stderr_bytes = result.stderr or b""
    try:
        stderr = stderr_bytes.decode("utf-8")
    except UnicodeDecodeError:
        stderr = stderr_bytes.decode("gbk", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(stderr.strip() or f"{provider} execution failed")
    return (
        _parse_codex(stdout, session_id)
        if provider == "codex"
        else _parse_claude(stdout, session_id)
    )


def is_missing_session_error(error_text: str) -> bool:
    value = error_text.lower()
    if provider_name() == "codex":
        return "no rollout found" in value or "thread/resume failed" in value
    return any(marker in value for marker in ("session not found", "no conversation found", "invalid session"))
