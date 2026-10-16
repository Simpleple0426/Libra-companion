"""Isolated real-model chat, retrieval and life-to-final-reply developer suite."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from evals.system_cases import CASES, VERSION
from evals.run_life_eval import save, settings, message_id


def fingerprint():
    files = {}
    for directory in ('application', 'domains', 'infrastructure', 'life_prototype', 'evals'):
        for path in sorted((BACKEND / directory).rglob('*')):
            if path.is_file() and path.suffix in {'.py', '.sql', '.json', '.md'}:
                files[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (ROOT / 'libra/world').glob('*.json'):
        files[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def worker(path):
    request = json.loads(Path(path).read_text(encoding='utf8'))
    case, output = request['case'], Path(request['output'])
    result = {'case_id': case['id'], 'category': case['category'], 'repeat': request['repeat'],
              'passed': False, 'execution_status': 'running', 'turns': [], 'requested_model': 'gpt-5.6-sol'}
    start = time.monotonic()
    world = None
    temporary = tempfile.TemporaryDirectory(prefix='libra-system-eval-', ignore_cleanup_errors=True)
    root = Path(temporary.name).resolve()
    from evals.system_world import isolate, ChatWorld
    isolate(root)
    from evals.system_transport import Conversation
    from evals.system_grading import memory_grade, reply_grade
    transport = Conversation(root / 'conversation', request['settings'], timeout=request['call_timeout'],
                             deadline=start + request['case_timeout'])
    try:
        chat = ChatWorld(root, embedding=request['embedding'])
        result['memory_ids'] = chat.identities
        if request['mode'] == 'prepare':
            result.update(passed=None, execution_status='prepared')
        elif case['category'] == 'memory':
            packet = chat.recall(case['query'], allowed_scopes=case['scopes'])
            result.update(packet=packet, grade=memory_grade(case, packet, chat.identities), execution_status='evaluated')
            result['passed'] = result['grade']['passed']
        else:
            turns = [{'text': case['text']}] if case['category'] == 'chat' else None
            if case['category'] == 'bridge':
                from evals.life_cases import CASES as LIFE_CASES
                from evals.life_world import World
                from life_prototype.cli_model import CliModel
                from life_prototype.operational_ledger import OperationalLedger
                class EvalModel(CliModel):
                    def command(self, cwd, schema):
                        args = super().command(cwd, schema)
                        return args[:-1] + ['-c', 'model_reasoning_effort="medium"', '-']
                class Budget(OperationalLedger):
                    def remaining(self):
                        return max(0, min(self.call_timeout_seconds, transport.deadline - time.monotonic()))
                    def reserve(self, stage):
                        if self.remaining() <= 0 or self._read()['attempts'] >= 36:
                            raise TimeoutError('life evaluation budget exhausted')
                        return super().reserve(stage)
                life_case = next(c for c in LIFE_CASES if c['id'] == case['life_case'])
                model = EvalModel(request['settings'], Budget(output / 'life-transport',
                                  call_timeout_seconds=request['call_timeout']), timeout=request['call_timeout'])
                world = World(root, model, initial_place=life_case.get('initial_place'))
                original_tool = world.engine.agent._tool
                def tool(step, name, args):
                    if name.startswith(('movies.', 'weread.')):
                        raise RuntimeError('external service outside evaluation scope')
                    return original_tool(step, name, args)
                world.engine.agent._tool = tool
                turns = life_case['turns']
            for index, turn in enumerate(turns):
                life_context, life_grade = None, None
                oracle = case.get('oracle', {})
                if world:
                    from evals.life_grading import grade_turn, business
                    ident = message_id(case['id'], request['repeat'], index)
                    before = world.snapshot()
                    world.app.submit_message(ident, turn['text'])
                    for tick in range(40):
                        if time.monotonic() >= transport.deadline:
                            raise TimeoutError('bridge scenario budget exhausted')
                        life_context = world.app.chat_context(message_id=ident)
                        review = life_context.get('daily_agenda_review') or {}
                        if review.get('status') in {'applied', 'none', 'clarify', 'failed', 'needs_review', 'expired'}:
                            break
                        world.app.tick(f'system-{index}-{tick}', max_steps=1)
                    after = world.snapshot()
                    life_grade = grade_turn(turn['expected'], before, after, review, life_context)
                    oracle = {'required': [], 'forbidden': [], 'tools': [],
                              'rubric': '准确依据生活回执回应。允许的操作状态为 ' + json.dumps(turn['expected']['status'], ensure_ascii=False)
                                        + '。applied 仅表示计划提交，不等于活动已完成；clarify 应澄清而非声称修改成功。'}
                payload, context, delivered, idempotent = chat.run_chat(case, transport, text=turn['text'], life_context=life_context)
                semantic = transport.review('\n'.join(payload.get('messages', [])), oracle, context)
                grade = reply_grade(oracle, payload, context, delivered, semantic)
                grade['checks']['idempotent_chat_delivery'] = idempotent
                if world:
                    grade['checks']['life_task_passed'] = life_grade['passed']
                    grade['checks']['reply_generation_did_not_change_life'] = business(after) == business(world.snapshot())
                if case.get('fault') in {'memory_timeout', 'weather_timeout'}:
                    target = 'memory.search' if case['fault'] == 'memory_timeout' else 'weather.current'
                    grade['checks']['fault_actually_observed'] = any(c.get('status') == 'failed' and c.get('tool') == target
                        for r in context['chat_research']['rounds'] for c in r.get('calls', []))
                if case.get('fault') == 'emotion_failure':
                    grade['checks']['fault_actually_observed'] = context['emotion_gate']['status'] == 'failed'
                grade['passed'] = all(grade['checks'].values())
                result['turns'].append({'input': turn['text'], 'payload': payload, 'context': context,
                    'delivered': delivered, 'semantic_review': semantic, 'grade': grade,
                    'life_grade': life_grade, 'life_before': before if world else None,
                    'life_after': after if world else None})
                save(output / 'result.json', result)
            result.update(execution_status='evaluated', passed=all(t['grade']['passed'] for t in result['turns']))
    except Exception as error:
        result.update(execution_status='error', error={'type': type(error).__name__, 'detail': str(error)[:300]})
        # Never store raw CLI stderr or credentials from an exception.
    finally:
        if world:
            world.close()
        gc.collect()
        for folder in ('host', 'world'):
            if (root / folder).exists():
                shutil.copytree(root / folder, output / folder, dirs_exist_ok=True)
        result['chat_calls'] = len(transport.records)
        result['usage'] = dict(sum((Counter(r.get('usage') or {}) for r in transport.records), Counter()))
        result['seconds'] = round(time.monotonic() - start, 3)
        result['life_calls'] = len(list((output / 'life-transport/calls').glob('*/record.json')))
        if (root / 'chat-calls.json').exists():
            shutil.copyfile(root / 'chat-calls.json', output / 'chat-calls.json')
        save(output / 'result.json', result)
        temporary.cleanup()
    return 0 if result['passed'] is not False else 1


def report(output, manifest, results):
    prepared = manifest['mode'] == 'prepare'
    lines = ['# Libra 系统评测', '', f"模式：{manifest['mode']}；模型：gpt-5.6-sol；reasoning：medium；检索：{manifest['embedding']}",
             '', '范围：生产聊天 Agent / 工具执行 / 情绪同步 / 回复投递模块，原生 LMC 召回，生活任务至最终回复。',
             '合成记忆和原文/天气适配器；不测提取模型、情绪判断质量、真实第三方服务、HTTP 或移动端。',
             '语义结果由独立模型评审，属于自动初评；未进行人工评审，不宣称人工验证或泛化性能。', '',
             '| 分类 | 完成/计划 | 自动初评通过 |', '|---|---:|---:|']
    for category in ('chat', 'memory', 'bridge'):
        rows = [r for r in results if r['category'] == category]
        planned = sum(c['category'] == category for c in manifest['cases']) * manifest['repeats']
        lines.append(f"| {category} | {len(rows)}/{planned} | {'未评分' if prepared else str(sum(r['passed'] is True for r in rows))} |")
    grades = [r['grade'] for r in results if r['category'] == 'memory' and 'grade' in r]
    recall = [g['recall_at_4'] for g in grades if g['recall_at_4'] is not None]
    mrr = [g['reciprocal_rank'] for g in grades if g['reciprocal_rank'] is not None]
    if recall:
        lines += ['', f"检索正例 {len(recall)} 条：Recall@4={sum(recall)/len(recall):.3f}；MRR@4={sum(mrr)/len(mrr):.3f}。过滤负例单独计数。"]
    lines += ['', '| 场景 | 重复 | 结果 | 证据 |', '|---|---:|---|---|']
    for r in results:
        folder = f"{r['case_id']}-r{r['repeat']}"
        label = 'PREPARED' if prepared else 'PASS' if r['passed'] else r['execution_status'].upper() if r['execution_status'] != 'evaluated' else 'FAIL'
        lines.append(f"| {r['case_id']} | {r['repeat']} | {label} | [trace]({folder}/result.json) |")
    values = sorted(r['seconds'] for r in results if r['category'] != 'memory')
    if values and not prepared:
        import math
        lines += ['', f"完整场景耗时 P50/P95：{values[math.ceil(len(values)*.5)-1]:.3f}/{values[math.ceil(len(values)*.95)-1]:.3f} 秒，包含评审调用及并发负载，不是线上回复延迟。"]
    lines += ['', '执行错误保留在计划分母中，源快照及输入预设冻结。不同 suite 或版本的报告不可当作同一轮总体成功率。']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    save(output / 'summary.json', {'mode': manifest['mode'], 'planned': len(manifest['cases'])*manifest['repeats'],
        'completed': len(results), 'passed': None if prepared else sum(r['passed'] is True for r in results), 'results': results})


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        return worker(sys.argv[2])
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--list', action='store_true')
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--live', action='store_true')
    parser.add_argument('--case', action='append')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--embedding', choices=('fts', 'local'), default='local')
    parser.add_argument('--case-timeout', type=int, default=600)
    parser.add_argument('--call-timeout', type=int, default=90)
    parser.add_argument('--cli-home', type=Path, help='Use an existing authenticated CLI profile; never copies credentials')
    args = parser.parse_args()
    chosen = [c for c in CASES if not args.case or c['id'] in args.case]
    if not chosen or (args.case and set(args.case) - {c['id'] for c in CASES}):
        parser.error('unknown case')
    if min(args.repeats, args.case_timeout, args.call_timeout) < 1:
        parser.error('budgets must be positive')
    if args.list:
        for case in chosen:
            print(case['id'], case['category'])
        return 0
    output = ROOT / 'output/system-evals' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    manifest = {'version': VERSION, 'mode': 'live' if args.live else 'prepare',
                'cases': chosen, 'repeats': args.repeats, 'workers': args.workers,
                'embedding': args.embedding, 'model': 'gpt-5.6-sol', 'reasoning': 'medium',
                'files': fingerprint(), 'settings': settings('gpt-5.6-sol'),
                'case_timeout': args.case_timeout, 'call_timeout': args.call_timeout,
                'limitations': ['Developer synthetic set, no holdout', 'No human review',
                    'Seeded validated memories, extraction not measured', 'Synthetic emotion results, appraisal quality not measured',
                    'Stubbed third-party services', 'Module composition, not HTTP/mobile E2E', 'Serving model identity not reported']}
    if args.cli_home:
        manifest['settings']['LIBRA_CODEX_HOME'] = str(args.cli_home.resolve())
    save(output / 'manifest.json', manifest)
    with zipfile.ZipFile(output / 'source-snapshot.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, digest in manifest['files'].items():
            data = (ROOT / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError('source changed during snapshot')
            archive.writestr(name, data)
    print('Report directory:', output, flush=True)
    jobs = [(case, repeat) for repeat in range(1, args.repeats + 1) for case in chosen]
    results = []
    def execute(job):
        case, repeat = job
        directory = output / f"{case['id']}-r{repeat}"
        directory.mkdir()
        request = {**manifest, 'case': case, 'repeat': repeat, 'output': str(directory)}
        save(directory / 'request.json', request)
        process, lifetime = None, None
        try:
            with (directory / 'worker.log').open('w', encoding='utf8') as log:
                from life_prototype.process_guard import ChildLifetime
                lifetime = ChildLifetime()
                process = subprocess.Popen([sys.executable, '-m', 'backend.evals.run_system_eval', '--worker', str(directory / 'request.json')],
                               cwd=ROOT, env={**os.environ, 'PYTHONUTF8': '1'}, stdout=log, stderr=log)
                lifetime.attach(process)
                process.wait(timeout=args.case_timeout + 180)
            path = directory / 'result.json'
            return json.loads(path.read_text(encoding='utf8')) if path.exists() else {'case_id': case['id'],
                'category': case['category'], 'repeat': repeat, 'passed': False, 'execution_status': 'worker_error', 'seconds': 0}
        except subprocess.TimeoutExpired:
            return {'case_id': case['id'], 'category': case['category'], 'repeat': repeat,
                    'passed': False, 'execution_status': 'worker_timeout', 'seconds': args.case_timeout + 180}
        finally:
            if lifetime:
                lifetime.close()
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(execute, job) for job in jobs]):
            r = future.result()
            results.append(r)
            report(output, manifest, results)
            print(r['case_id'], r['execution_status'], r['passed'], flush=True)
    return 0 if all(r['execution_status'] == 'prepared' if args.prepare else r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
