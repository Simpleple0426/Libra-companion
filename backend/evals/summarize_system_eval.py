"""Combine completed family reports without silently regrading failures."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from evals.run_life_eval import save


def combine(system_dir, life_dir, output):
    system_dir, life_dir, output = map(lambda p: Path(p).resolve(), (system_dir, life_dir, output))
    system = json.loads((system_dir / 'summary.json').read_text(encoding='utf8'))
    sm = json.loads((system_dir / 'manifest.json').read_text(encoding='utf8'))
    life = json.loads((life_dir / 'summary.json').read_text(encoding='utf8'))
    lm = life['manifest']
    if system['mode'] != 'live' or lm['mode'] != 'live':
        raise ValueError('preparation reports have no quality score')
    if len(system['results']) != system['planned'] or len(life['results']) != lm['planned']['runs']:
        raise ValueError('incomplete reports cannot be combined as a finished baseline')
    prefixes = ('backend/application/', 'backend/infrastructure/', 'backend/life_prototype/', 'libra/world/')
    common = {name: digest for name, digest in lm['source']['files'].items() if name.startswith(prefixes)}
    mismatches = [name for name, digest in common.items() if sm['files'].get(name) != digest]
    if mismatches:
        raise ValueError('tested production source differs: ' + ','.join(mismatches))
    if lm['model'] != sm['model'] or lm['reasoning'] != sm['reasoning']:
        raise ValueError('model settings differ')
    groups = {kind: [r for r in system['results'] if r['category'] == kind] for kind in ('chat', 'memory', 'bridge')}
    groups['life'] = life['results']
    turns = [t for r in system['results'] for t in r.get('turns', [])]
    semantic = [t['semantic_review'] for t in turns]
    failures = [{'case_id': r['case_id'], 'category': family,
                 'source': str((system_dir if family != 'life' else life_dir) / f"{r['case_id']}-r{r['repeat']}" / 'result.json')}
                for family, rows in groups.items() for r in rows if r['passed'] is not True]
    result = {'model': sm['model'], 'reasoning': sm['reasoning'], 'planned': system['planned'] + lm['planned']['runs'],
              'scenario_count': len(sm['cases']) + len(lm['cases']),
              'repeats': {'system': sm['repeats'], 'life': lm['planned']['repeats']},
              'production_source_files_matched': len(common),
              'families': {k: {'completed': len(v), 'passed': sum(r['passed'] is True for r in v),
                               'execution_errors': sum(r['execution_status'] != 'evaluated' for r in v)} for k, v in groups.items()},
              'semantic_initial_review': {'replies': len(semantic),
                  'grounded': sum(v['grounded'] is True for v in semantic),
                  'false_success': sum(v['false_success'] is True for v in semantic),
                  'human_reviewed': False}, 'failures': failures,
              'sources': {'system': str(system_dir), 'life': str(life_dir)},
              'limitations': sm['limitations']}
    output.parent.mkdir(parents=True, exist_ok=True)
    save(output.with_suffix('.json'), result)
    import os
    link = lambda path: os.path.relpath(path, output.parent).replace('\\', '/')
    day = datetime.strptime(lm['started_at'], '%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date()
    lines = [f'# Libra 分项评测基线（{day}）', '',
             f"完成 {result['scenario_count']} 个分项开发场景，共 {result['planned']} 次运行。",
             f"请求模型固定 {sm['model']}，reasoning {sm['reasoning']}；新增系统场景重复 {sm['repeats']} 次，生活场景重复 {lm['planned']['repeats']} 次。",
             '两份报告共用的生产模块与世界配置源码哈希已核对一致；评测脚本版本各自保留在快照中。', '',
             '| 分类 | 通过/完成运行 | 判定方式 |', '|---|---:|---|']
    labels = {'chat': '聊天', 'memory': '长期记忆检索', 'life': '生活执行', 'bridge': '生活至最终回复'}
    for family in ('chat', 'memory', 'life', 'bridge'):
        row = result['families'][family]
        method = '程序断言 + 自动语义初评' if family in {'chat', 'bridge'} else '程序断言'
        lines.append(f"| {labels[family]} | {row['passed']}/{row['completed']} | {method} |")
    lines += ['', '## 执行成功与回复一致性分别计分', '',
              f"本轮 {len(semantic)} 条最终回复的自动语义初评均有记录；有据回复 {result['semantic_initial_review']['grounded']}/{len(semantic)}，虚报成功 {result['semantic_initial_review']['false_success']}/{len(semantic)}。",
              '评审使用同一请求模型的独立新会话，属于自动初评，未由人工标注员复核，不能宣称泛化准确率。', '',
              '## 保留的失败', '']
    for failure in failures:
        lines.append(f"- `{failure['case_id']}`：[{failure['category']} 原始轨迹]({link(failure['source'])})。")
    lines += ['', '任务成功与回复一致性分别判分；回复准确说明失败，不会将未完成任务改判为成功。没有通过重跑挑选成功结果替代失败。', '',
              '禁止修改、恢复与记忆检索指标及其样本量，见原始分项报告。小型合成开发集不代表真实历史记忆检索效果。', '',
              '## 证据与复现', '',
              f"- [系统原始报告]({link(system_dir / 'report.md')})：源码快照、预设、回复、工具轨迹、数据库和自动评审。",
              f"- [生活原始报告]({link(life_dir / 'report.md')})：30 场景及每条断言。",
              '- CLI 专用 profile 本轮刷新凭据失效，正式基线显式使用当前用户另一份已有登录；模型和应用配置未切换。',
              '- 历史开发轮次与登录失败记录不纳入本基线，不覆盖原始文件。', '',
              '## 简历表述', '',
              f"构建覆盖聊天工具调用、长期记忆检索、生活执行及跨链路回复的 {result['scenario_count']} 场景分项评测，结合数据库状态断言、消息关联校验与自动语义评审，验证事实纠正、来源隔离、查询超时及持久化恢复；区分任务执行成功与回复一致性，保留失败轨迹并定位原因。", '',
              '## 覆盖边界', '',
              '测试组合实际聊天编排、工具执行、情绪同步、记忆存储/召回、生活调度和回复投递模块；不是 HTTP 或移动端全应用端到端评测。',
              '记忆使用已通过候选写入校验的合成预设，不测提取模型质量。天气/原文为可控适配器，情绪为合成结果，不测真实外部服务或情绪判断质量。',
              '尚无留出集、人工语义标注、完整重复稳定性结论或模型权重哈希；耗时包括模型评审与并发负载，不能直接写成线上单条回复延迟。']
    output.write_text('\n'.join(lines) + '\n', encoding='utf8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--system', required=True, type=Path)
    parser.add_argument('--life', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = combine(args.system, args.life, args.output)
    print(json.dumps(result['families'], ensure_ascii=False))


if __name__ == '__main__':
    main()
