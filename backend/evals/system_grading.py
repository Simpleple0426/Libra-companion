"""Deterministic metrics plus explicitly separate provisional semantic review."""
import re


def memory_grade(case, packet, identities):
    ranked = [m['memory_id'] for m in packet.get('memories', [])][:4]
    relevant = {identities[k] for k in case['relevant']}
    banned = {identities[k] for k in case['forbidden']}
    hit = relevant.intersection(ranked)
    checks = {'required_recall': relevant.issubset(ranked),
              'no_forbidden_memory': not banned.intersection(ranked),
              'scope_isolation': all(m['primary_scope'] in case['scopes'] for m in packet.get('memories', [])),
              'evidence_provenance': all(m.get('source_experience_ids') and m.get('source_times')
                                         for m in packet.get('memories', [])),
              'no_retrieval_degradation': not packet.get('degraded')}
    return {'passed': all(checks.values()), 'checks': checks,
            'recall_at_4': len(hit) / len(relevant) if relevant else None,
            'reciprocal_rank': next((1 / (i + 1) for i, mid in enumerate(ranked) if mid in relevant), 0) if relevant else None,
            'ranked_ids': ranked}


def reply_grade(oracle, payload, context, delivered, semantic):
    messages = payload.get('messages') if isinstance(payload, dict) else None
    valid = isinstance(messages, list) and bool(messages) and all(isinstance(m, str) and m.strip() for m in messages)
    text = '\n'.join(messages) if valid else ''
    calls = [c for r in context.get('chat_research', {}).get('rounds', []) for c in r.get('calls', [])]
    tools = {c['tool'] for c in calls if c.get('status') != 'duplicate_skipped'}
    checks = {'valid_nonempty_reply': valid and 'calls' not in payload,
              'required_content': all(s in text for s in oracle.get('required', [])),
              'forbidden_content_absent': all(s not in text for s in oracle.get('forbidden', [])),
              'required_tools_used': set(oracle.get('tools', [])).issubset(tools),
              'bounded_tool_rounds': len(context.get('chat_research', {}).get('rounds', [])) <= 3
                                    and all(len(r.get('calls', [])) <= 2 for r in context.get('chat_research', {}).get('rounds', [])),
              'emotion_joined_before_delivery': context.get('emotion_gate', {}).get('received') is True,
              'persisted_reply_matches': [m['content'] for m in delivered] == messages,
              'semantic_review': bool(semantic and semantic.get('grounded') is True and semantic.get('answers_request') is True
                                      and semantic.get('false_success') is False)}
    return {'passed': all(checks.values()), 'checks': checks, 'reply': text,
            'semantic_review_is_provisional': True, 'tools': sorted(tools)}
