"""Run from repository root: python -m backend.evals.run_life_eval --help."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime, timezone

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from evals.life_cases import CASES, VERSION, SMOKE
from evals.life_grading import grade_turn, business, summarize


def message_id(case_id, repeat, turn):
    """Opaque deterministic transport IDs; do not give the model case labels."""
    return 'm_' + hashlib.sha256(f'{case_id}:{repeat}:{turn}'.encode()).hexdigest()[:24]


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    temporary.replace(path)


def fingerprint():
    files = {}
    for directory in ('life_prototype', 'application', 'infrastructure', 'evals'):
        for path in sorted((BACKEND / directory).rglob('*')):
            if path.is_file() and path.suffix in {'.py', '.json', '.sql', '.md'}:
                files[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted((ROOT / 'libra' / 'world').glob('*.json')):
        files[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), 'files': files}


def settings(model):
    # Read only the existing transport's two non-secret configuration values.
    # No production module import: infrastructure.paths would load the full env.
    from dotenv import dotenv_values
    env_path = Path(os.environ.get('LIBRA_ENV_FILE') or
                    Path(os.environ.get('LIBRA_CONFIG_DIR') or ROOT / 'config') / '.env')
    values = dotenv_values(env_path)
    result = {key: os.environ.get(key) or values.get(key) for key in ('LIBRA_CODEX_COMMAND', 'LIBRA_CODEX_HOME')}
    return {**{k: v for k, v in result.items() if v}, 'LIBRA_LLM_MODEL': model}


def worker(request_path):
    import faulthandler
    faulthandler.enable()
    request = json.loads(Path(request_path).read_text(encoding='utf8'))
    output = Path(request['output'])
    temporary = tempfile.TemporaryDirectory(prefix='libra-life-eval-', ignore_cleanup_errors=True)
    runtime_root = Path(temporary.name).resolve()
    from evals.life_world import isolate, World
    isolate(runtime_root)
    from life_prototype.cli_model import CliModel
    from life_prototype.operational_ledger import OperationalLedger
    from life_prototype.model_client import ModelError

    class Budget(OperationalLedger):
        def remaining(self):
            return max(0, min(self.call_timeout_seconds, deadline - time.monotonic()))

        def reserve(self, stage):
            if self.remaining() <= 0 or self._read()['attempts'] >= request['max_model_calls']:
                raise ModelError('evaluation scenario budget exhausted')
            super().reserve(stage)

    class EvalModel(CliModel):
        def command(self, cwd, schema):
            command = super().command(cwd, schema)
            return command[:-1] + ['-c', 'model_reasoning_effort="' + request['reasoning'] + '"', '-']

    start = time.monotonic()
    deadline = start + request['case_timeout']
    budget = Budget(output / 'transport', call_timeout_seconds=request['call_timeout'])
    model = EvalModel(request['settings'], budget, timeout=request['call_timeout'])
    case = request['case']
    result = {'case_id': case['id'], 'category': case['category'], 'repeat': request['repeat'],
              'execution_status': 'running', 'passed': False, 'turns': [],
              'fault': case.get('fault'), 'fault_injected': False,
              'requested_model': request['settings']['LIBRA_LLM_MODEL'],
              'reported_model': None, 'model_identity_evidence': 'CLI --model argument; CLI does not return serving model identity',
              'scope': 'life_inbox_scheduler_agent_commit_outbox_chat_context',
              'production_chat_reply': None}
    world = None

    def install_faults():
        original = world.engine.agent._tool

        def invoke(step, name, args):
            # This suite contains no content-discovery requests. Fail explicitly
            # if the agent nevertheless attempts an external content service.
            if name.startswith(('movies.', 'weread.')):
                raise RuntimeError('external content service outside evaluation scope')
            if case.get('fault') == 'read_timeout' and not result['fault_injected'] and name in {'state.read', 'messages.read', 'agenda.read'}:
                result['fault_injected'] = True
                raise TimeoutError('injected one-shot read timeout before side effects')
            return original(step, name, args)
        world.engine.agent._tool = invoke

    def restart():
        nonlocal world
        world.close()
        world = World(runtime_root, model, reopen=True, initial_place=case.get('initial_place'))
        install_faults()
        result['fault_injected'] = True

    try:
        world = World(runtime_root, model, initial_place=case.get('initial_place'))
        install_faults()
        result['initial'] = world.snapshot()
        save(output / 'initial.json', result['initial'])
        if request['mode'] == 'prepare':
            result.update(execution_status='prepared', passed=None)
            return result
        for index, turn in enumerate(case['turns']):
            ident = message_id(case['id'], request['repeat'], index)
            before = world.snapshot()
            delivery = world.app.submit_message(ident, turn['text'])
            if case.get('fault') == 'duplicate':
                world.app.submit_message(ident, turn['text'])
                result['fault_injected'] = True
            if case.get('fault') == 'restart_queued':
                restart()
            ticks = []
            terminal_seconds = None
            turn_start = time.monotonic()
            for tick in range(40):
                if time.monotonic() >= deadline:
                    raise TimeoutError('scenario wall budget exhausted')
                context = world.app.chat_context(message_id=ident)
                review = context.get('daily_agenda_review') or {}
                if delivery.get('receipt') and delivery['receipt'].get('status') == 'ended':
                    review = {'status': 'host_ended', 'message_id': 'app:' + ident + ':ordinary'}
                if review.get('status') in {'applied', 'none', 'clarify', 'failed', 'host_ended', 'needs_review', 'expired'}:
                    terminal_seconds = time.monotonic() - turn_start
                    break
                ticks.append(world.app.tick(f'eval-{index}-{tick}', max_steps=1))
            after = world.snapshot()
            context = world.app.chat_context(message_id=ident)
            review = context.get('daily_agenda_review') or {}
            if delivery.get('receipt') and delivery['receipt'].get('status') == 'ended':
                review = {'status': 'host_ended', 'message_id': 'app:' + ident + ':ordinary'}
            grade = grade_turn(turn['expected'], before, after, review, context)
            grade['checks']['terminal_within_budget'] = terminal_seconds is not None
            grade['checks']['single_inbox_delivery'] = sum(r['id'] == ident + ':ordinary' for r in after['inbox']) == 1
            grade['passed'] = all(grade['checks'].values())
            grade['failed_checks'] = [k for k, v in grade['checks'].items() if not v]
            result['turns'].append({'message_id': ident, 'text': turn['text'], 'expected': turn['expected'],
                                    'before': before, 'after': after, 'context': context, 'review': review,
                                    'grade': grade, 'ticks': ticks, 'terminal_seconds': terminal_seconds})
            save(output / 'result.json', result)
            if case.get('fault') == 'restart_committed':
                restart()
                world.app.submit_message(ident, turn['text'])
                recovered = world.snapshot()
                result['restart_preserved'] = business(after) == business(recovered) and after['inbox'] == recovered['inbox']
        result.update(execution_status='evaluated', passed=all(t['grade']['passed'] for t in result['turns']))
        if case.get('fault'):
            result['passed'] &= result['fault_injected'] and result.get('restart_preserved', True)
        result['final'] = world.snapshot()
    except Exception as error:
        result.update(execution_status='error', error={'type': type(error).__name__, 'detail': str(error)[:1500]})
        import traceback
        (output / 'error.txt').write_text(traceback.format_exc(), encoding='utf8')
    finally:
        faulthandler.cancel_dump_traceback_later()
        try:
            if world:
                world.close()
            import gc
            gc.collect()  # sqlite3 transaction contexts do not close host read handles.
            # Keep FULL SQLite durability. Archive closed synthetic databases.
            for name in ('world', 'host'):
                if (runtime_root / name).exists():
                    shutil.copytree(runtime_root / name, output / name, dirs_exist_ok=True)
        except Exception as error:
            result.update(execution_status='artifact_error', passed=False,
                          artifact_error={'type': type(error).__name__, 'detail': str(error)[:500]})
        finally:
            temporary.cleanup()
        result['duration_seconds'] = round(time.monotonic() - start, 3)
        result['model_calls'] = budget._read()['attempts']
        result['provider_blocked'] = budget._read().get('blocked')
        usages = []
        for record in (output / 'transport' / 'calls').glob('*/record.json'):
            body = json.loads(record.read_text(encoding='utf8'))
            if body.get('usage'):
                usages.append(body['usage'])
        result['usage_totals'] = dict(sum((Counter(u) for u in usages), Counter()))
        result['calls_with_usage'] = len(usages)
        save(output / 'result.json', result)
    return result


def report(output, manifest, results):
    summary = summarize(results, manifest['planned'])
    save(output / 'summary.json', {'manifest': manifest, 'summary': summary, 'results': results})
    lines = ['# Life Agent 评测报告', '', f"- 模式：{manifest['mode']}；请求模型：{manifest['model']}；reasoning：{manifest['reasoning']}",
             f"- 并发测试进程：{manifest.get('workers', 1)}；耗时受该并发负载影响。",
             '- 范围：消息投递 → 调度器 → Agent → 工具提交 → outbox → 聊天上下文回执。',
             '- 未覆盖生产聊天回复生成；虚报成功率未测量。CLI 未回传服务端模型标识。',
             f"- 完成：{len(results)}/{manifest['planned']['runs']}；通过：{summary['passed_runs']}；全重复通过场景：{summary['all_repeats_passed_cases']}/{manifest['planned']['cases']}",
             f"- 代码指纹：`{manifest['source']['sha256']}`", '',
             '| 类别 | 运行数 | 通过 | 执行错误 |', '|---|---:|---:|---:|']
    for name, bucket in summary['by_category'].items():
        lines.append(f"| {name} | {bucket['runs']} | {bucket['passed']} | {bucket['errors']} |")
    lines += ['', f"禁止写入场景：{summary['wrong_write_turns']}/{summary['no_write_turns']} 轮出现错误写入。",
              f"场景耗时 P50/P95：{summary['latency_p50_seconds']} / {summary['latency_p95_seconds']} 秒。",
              '样本量较小时，P95 接近最大值；各场景轮数不同，不代表线上单条回复延迟。', '', '## 逐次结果', '',
              '| 用例 | 重复 | 结果 | 模型调用 | 证据 |', '|---|---:|---|---:|---|']
    failures = []
    for r in results:
        label = 'PASS' if r.get('passed') else r['execution_status'] if r['execution_status'] != 'evaluated' else 'FAIL'
        lines.append(f"| {r['case_id']} | {r['repeat']} | {label} | {r.get('model_calls', 0)} | [trace]({r['artifact']}/result.json) |")
        failed = [f"turn {i + 1}: {', '.join(t['grade']['failed_checks'])}" for i, t in enumerate(r.get('turns', [])) if not t['grade']['passed']]
        if failed:
            failures.append(f"- {r['case_id']}: {'; '.join(failed)}")
        if r.get('error'):
            failures.append(f"- {r['case_id']}: {r['error']}")
    if failures:
        lines += ['', '## 失败定位', '', *failures]
    if manifest['mode'] != 'live':
        lines += ['', '**这是环境准备自检，没有模型质量分数，不可用于简历成功率。**']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--live', action='store_true', help='Call the real model using existing CLI authentication')
    modes.add_argument('--prepare', action='store_true', help='Prepare isolated worlds without model calls')
    modes.add_argument('--list', action='store_true', help='List versioned cases without model calls')
    parser.add_argument('--suite', choices=['smoke', 'full'], default='smoke')
    parser.add_argument('--case', action='append', help='Select an exact case ID (repeatable)')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=1, help='Independent scenario processes; affects latency')
    parser.add_argument('--model', choices=['gpt-5.6-sol'], default='gpt-5.6-sol')
    parser.add_argument('--reasoning', choices=['low', 'medium', 'high'], default='medium')
    parser.add_argument('--case-timeout', type=int, default=600)
    parser.add_argument('--call-timeout', type=int, default=90)
    parser.add_argument('--max-model-calls', type=int, default=36)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if min(args.repeats, args.case_timeout, args.call_timeout, args.max_model_calls) < 1:
        parser.error('budgets and repeats must be positive')
    known = {c['id'] for c in CASES}
    if args.case and set(args.case) - known:
        parser.error('unknown case IDs: ' + ', '.join(set(args.case) - known))
    chosen = [c for c in CASES if c['id'] in args.case] if args.case else [c for c in CASES if args.suite == 'full' or c['id'] in SMOKE]
    if args.list:
        for c in chosen:
            print(c['id'], c['category'], len(c['turns']))
        return 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = (args.output or ROOT / 'output' / 'life-evals' / stamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cli = settings(args.model)
    manifest = {'schema_version': 1, 'suite_version': VERSION, 'started_at': stamp,
                'mode': 'live' if args.live else 'prepare', 'model': args.model, 'reasoning': args.reasoning, 'workers': args.workers,
                'planned': {'cases': len(chosen), 'repeats': args.repeats, 'runs': len(chosen) * args.repeats},
                'cases': chosen, 'source': fingerprint(),
                'budgets': {'case_seconds': args.case_timeout, 'call_seconds': args.call_timeout, 'model_calls_per_case': args.max_model_calls},
                'scope': 'life_inbox_scheduler_agent_commit_outbox_chat_context',
                'limitations': ['No production chat generation or delivery', 'Synthetic worlds and frozen business clock',
                                'No live third-party content services', 'Restart cases reopen runtime objects; not OS process crash tests',
                                'Requested model recorded; CLI does not report serving model identity']}
    if args.live:
        from life_prototype.cli_model import preflight
        manifest['preflight'] = preflight(cli)
        save(output / 'manifest.json', manifest)
        if not all(manifest['preflight'][k] for k in ('authenticated', 'required_flags_supported')):
            print('CLI preflight failed; see', output / 'manifest.json')
            return 2
    save(output / 'manifest.json', manifest)
    with zipfile.ZipFile(output / 'source-snapshot.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, expected_hash in manifest['source']['files'].items():
            source = (ROOT / name).read_bytes()
            if hashlib.sha256(source).hexdigest() != expected_hash:
                raise RuntimeError('source changed while creating snapshot: ' + name)
            archive.writestr(name, source)
        archive.write(output / 'manifest.json', 'evaluation-manifest.json')
    results = []
    print('Report directory:', output, flush=True)
    stop = threading.Event()

    def execute(job):
        number, repeat, case = job
        if stop.is_set():
            return None
        directory = output / f"{case['id']}-r{repeat}"
        directory.mkdir()
        request = {'case': case, 'repeat': repeat, 'output': str(directory), 'settings': cli,
                   'mode': manifest['mode'], 'reasoning': args.reasoning,
                   'case_timeout': args.case_timeout, 'call_timeout': args.call_timeout,
                   'max_model_calls': args.max_model_calls}
        save(directory / 'request.json', request)
        print(f"[{number}/{manifest['planned']['runs']}] {case['id']} r{repeat}", flush=True)
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
        with (directory / 'worker.log').open('w', encoding='utf8') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(directory / 'request.json')],
                                       cwd=ROOT, env=env, stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
            try:
                process.wait(timeout=args.case_timeout + 30)
            except subprocess.TimeoutExpired:
                from life_prototype.cli_model import stop_process
                stop_process(process)
            except BaseException:
                from life_prototype.cli_model import stop_process
                stop_process(process)
                raise
        path = directory / 'result.json'
        r = json.loads(path.read_text(encoding='utf8')) if path.exists() else {
            'case_id': case['id'], 'category': case['category'], 'repeat': repeat, 'passed': False,
            'execution_status': 'worker_failed', 'error': {'type': 'WorkerExit', 'returncode': process.returncode}}
        if r['execution_status'] == 'running':
            r.update(execution_status='worker_failed', passed=False,
                     error={'type': 'IncompleteWorkerResult', 'returncode': process.returncode})
        r['artifact'] = directory.name
        save(path, r)
        if r.get('provider_blocked'):
            stop.set()
        return r

    jobs = [(repeat, case) for repeat in range(1, args.repeats + 1) for case in chosen]
    order = {(case['id'], repeat): index for index, (repeat, case) in enumerate(jobs)}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(execute, (index + 1, repeat, case)) for index, (repeat, case) in enumerate(jobs)]
        for future in as_completed(futures):
            r = future.result()
            if r is None:
                continue
            results.append(r)
            results.sort(key=lambda row: order[(row['case_id'], row['repeat'])])
            report(output, manifest, results)
            label = 'NO MODEL SCORE' if r['execution_status'] == 'prepared' else 'PASS' if r.get('passed') else 'NOT PASS'
            print(' ', r['case_id'], r['execution_status'], label, 'calls:', r.get('model_calls', 0), flush=True)
    if stop.is_set():
        print('Provider block; stopped without fallback or budget reset.', flush=True)
        return 2
    return 0 if all(r.get('passed') or r['execution_status'] == 'prepared' for r in results) else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
    else:
        raise SystemExit(main())
