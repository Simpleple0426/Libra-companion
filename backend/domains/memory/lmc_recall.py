"""Primary LMC recall with graph/E/perception and retained candidate supplements.

literal_raw is a compatibility argument only; raw records are never recall hits.
"""
from .base import *
import logging
from .lmc import active_rows, SAFE_RELATIONS, RELATION_WEIGHTS


def source_times(sources):
    """Expose evidence timestamps in the user's timezone, not inferred event dates."""
    local = timezone(timedelta(hours=8))
    return [dict(experience_id=s['experience_id'], actor=s['actor'],
                 reported_at=datetime.fromisoformat(s['occurred_at'].replace('Z', '+00:00'))
                 .astimezone(local).isoformat()) for s in sources]


TIME_HINT = '证据时间为北京时间的发言/来源时间；实际发生时间以原话为准，计划不代表已发生。'


def graph(c, seeds, eligible, hops):
    frontier, seen, hits, paths = list(seeds)[:8], set(seeds), [], {}
    weights = {mid: 1. for mid in seeds}
    for depth in range(1, min(2, max(0, int(hops))) + 1):
        following = []
        for mid in frontier:
            for edge in c.execute('''SELECT * FROM lmc_memory_relations WHERE status='active'
                AND (source_id=? OR target_id=?) AND strength>? ORDER BY strength DESC LIMIT 20''',
                (mid, mid, .4 if depth == 1 else .7)):
                if edge['relation_type'] not in SAFE_RELATIONS:
                    continue
                source, target = eligible.get(edge['source_id']), eligible.get(edge['target_id'])
                if not source or not target or source['status'] != 'current' or target['status'] != 'current' or source['revision'] != edge['source_revision'] or target['revision'] != edge['target_revision']:
                    continue
                other = edge['target_id'] if mid == edge['source_id'] else edge['source_id']
                if other in seen:
                    continue
                seen.add(other)
                hits.append(other)
                following.append(other)
                weights[other] = weights[mid] * edge['strength'] * RELATION_WEIGHTS[edge['relation_type']] * .8
                paths[other] = paths.get(mid, []) + [dict(edge, activation=weights[other])]
                if len(hits) >= 10:
                    return sorted(hits, key=weights.get, reverse=True), paths
        frontier = following[:8]
    return sorted(hits, key=weights.get, reverse=True), paths


def recall(store, query, *, thread_id=None, session_id=None, recent_messages=(), budget=2200,
           limit=4, allowed_sensitivity=('normal',), allowed_scopes=('user', 'self', 'shared'),
           request_id=None, graph_hops=2, query_expansion=False, emotion_resonance=True,
           literal_raw=True, fusion='rrf', spontaneous=True,
           adaptive_search=True, query_weights=None, channel_weights=None, query_plan=None):
    started = time.perf_counter()
    if fusion != 'rrf':
        raise ValidationError('unsupported_fusion')
    query = str(query).strip()[:3000]
    budget, limit = max(512, int(budget)), max(0, min(10, int(limit)))
    packet = {'request_id': request_id or uid('recall'), 'query_intent': 'contextual',
              'memories': [], 'conflicts': [], 'degraded': [],
              'omitted': {'duplicate_count': 0, 'filtered_count': 0}}
    trace = {'engine': 'lmc5-native-v2', 'fusion': 'rrf', 'channels': {}, 'selected_ids': [], 'paths': {}}
    if not query or limit == 0:
        packet['query_intent'] = 'no_memory_needed'
        return packet
    output_limit, output_budget = limit, budget
    if store.relevance_model:
        limit, budget = 10, max(budget, 30000)
    if CORRECTION.search(query):
        packet['query_intent'] = 'current_correction'
    explicit = bool(RECALL_CUE.search(query))
    if explicit:
        packet['query_intent'] = 'explicit_memory_request'
    from .recall_queries import plan, fallback_queries, fuse, QUERY_WEIGHTS, CHANNEL_WEIGHTS
    planned = [dict(item) for item in query_plan] if query_plan else (plan(query, recent_messages) if adaptive_search else [{'text': query, 'kind': 'original'}])
    # Explicit legacy expansion remains opt-in; automatic planning uses only evidence.
    if query_expansion and store.query_expander:
        try:
            expansion = store.query_expander(query)
            expansion = [expansion] if isinstance(expansion, str) else list(expansion or [])
            for text in expansion[:2]:
                if isinstance(text, str) and text.strip() and text.strip() not in {p['text'] for p in planned}:
                    planned.append({'text': text.strip()[:3000], 'kind': 'fallback'})
        except Exception:
            packet['degraded'].append('query_expansion_unavailable')
    queries = [item['text'] for item in planned]
    recent_ids = {str(m.get('id')) for m in recent_messages if m.get('id') is not None}
    recent_text = '\n'.join(str(m.get('content', '')) for m in recent_messages)
    with store.connect() as c:
        rows = {}
        source_map = {}
        session = session_id or thread_id
        # A persistent provider session is not a recall cooldown boundary.
        # Selection logs remain diagnostic; only this packet deduplicates hits.
        pending = [r[0] for r in c.execute('''SELECT content FROM raw_experiences
            WHERE actor='user' AND source_status='active' AND (segmented=0 OR EXISTS
                (SELECT 1 FROM segment_experiences se JOIN experience_segments es USING(segment_id)
                 WHERE se.experience_id=raw_experiences.experience_id AND es.segment_state IN ('open','closed')))
            ORDER BY rowid DESC LIMIT 100''') if CORRECTION.search(r[0])]
        if CORRECTION.search(query):
            pending.append(query)
        historical = bool(re.search(r'以前|原来|过去|当时|旧的|之前住|之前的', query))
        for raw in active_rows(store, c, include_history=historical):
            row = dict(raw)
            mid = row['memory_id']
            sources = [dict(s) for s in c.execute('''SELECT r.* FROM lmc_sources s
                JOIN raw_experiences r USING(experience_id) WHERE s.memory_id=?''', (mid,))]
            if (row['primary_scope'] not in allowed_scopes or row['sensitivity'] not in allowed_sensitivity
                    or row['confidence'] < .6 or any(overlap(q, row['content']) > .15 for q in pending)):
                packet['omitted']['filtered_count'] += 1
                continue
            if row['content'] in recent_text or all(s['source_system'] == 'libra_chat' and str(s['source_id']) in recent_ids for s in sources):
                packet['omitted']['duplicate_count'] += 1
                continue
            rows[mid], source_map[mid] = row, sources
        stored_vectors = {}
        if store.embedding_adapter:
            adapter = store.embedding_adapter
            for entry in c.execute('SELECT * FROM lmc_embeddings WHERE model_id=? AND dimensions=? AND tokenizer_version=?',
                                   (adapter.model_id, adapter.dimensions, TOKENIZER_VERSION)):
                mid = entry['memory_id']
                if mid not in rows or rows[mid]['revision'] != entry['revision']:
                    continue
                try:
                    vector = json.loads(entry['vector_json'])
                    if len(vector) == adapter.dimensions:
                        stored_vectors[mid] = vector
                except (TypeError, ValueError):
                    packet['degraded'].append('invalid_vector')

        candidate_limit = 32
        document_terms = {mid: identity_tokens(row['title'] + ' ' + row['content'])
                          for mid, row in rows.items()}

        def search(item):
            text = item['text']
            dense = {}
            if store.embedding_adapter:
                try:
                    vector = store._embed(text)
                    dense = {mid: sum(a*b for a,b in zip(vector, stored)) for mid, stored in stored_vectors.items()}
                    dense = {mid: score for mid, score in dense.items() if math.isfinite(score) and score >= .3}
                except Exception as error:
                    packet['degraded'].append('vector_unavailable')
                    packet.setdefault('vector_errors', []).append({'type': type(error).__name__, 'message': str(error)[:200]})
                    logging.getLogger(__name__).warning('LMC vector recall failed (%s): %s', type(error).__name__, error)
            query_terms = identity_tokens(text)
            lexical = {mid: len(query_terms & terms) / max(1, min(len(query_terms), len(terms)))
                       for mid, terms in document_terms.items()}
            sparse = []
            terms = sorted(query_terms)[:80]
            if store.fts_available and terms:
                try:
                    match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
                    # FTS5 rank defaults to BM25. Apply eligibility before the
                    # candidate cap so hidden/old records cannot crowd out hits.
                    cursor = c.execute('SELECT memory_id FROM lmc_fts WHERE lmc_fts MATCH ? ORDER BY rank', (match,))
                    try:
                        for result in cursor:
                            mid = result[0]
                            if mid in rows and lexical[mid] >= .16:
                                sparse.append(mid)
                                if len(sparse) >= candidate_limit:
                                    break
                    finally:
                        cursor.close()
                except sqlite3.Error:
                    packet['degraded'].append('sparse_unavailable')
            if not sparse:
                sparse = sorted((mid for mid in rows if lexical[mid] >= .16), key=lexical.get, reverse=True)
            channels = {'vector': sorted(dense, key=dense.get, reverse=True)[:candidate_limit],
                        'fts': sparse[:candidate_limit]}
            # One strong relevant result is enough; do not fill a quota.
            strong = max(dense.values(), default=0) >= .6 or max(lexical.values(), default=0) >= .45
            return channels, strong, max(dense.values(), default=0)

        searches, attempts = [], []
        sufficient, top = False, 0
        for item in planned:
            found, strong, peak = search(item)
            searches.append((item['kind'], found))
            attempts.append({**item, 'channels': found, 'sufficient': strong})
            sufficient, top = sufficient or strong, max(top, peak)
        supplemental = fallback_queries(planned) if adaptive_search and not sufficient else []
        for item in supplemental:
            found, strong, peak = search(item)
            searches.append((item['kind'], found))
            attempts.append({**item, 'channels': found, 'sufficient': strong})
            queries.append(item['text'])
            top = max(top, peak)
            if strong:
                break
        channels = {name: list(dict.fromkeys(mid for _, found in searches for mid in found[name]))
                    for name in ('vector', 'fts')}
        trace.update(candidate_limit=candidate_limit, sparse_ranker='fts5_bm25',
                     search_attempts=attempts, supplemental_reason=None if sufficient else 'weak_or_missing_direct_evidence',
                     query_weights={**QUERY_WEIGHTS, **(query_weights or {})},
                     channel_weights={**CHANNEL_WEIGHTS, **(channel_weights or {})})
        paths = {}
        if graph_hops:
            channels['graph'], paths = graph(c, channels['vector'] + channels.get('fts', []), rows, graph_hops)
        coordinate = emotion_coordinate(query) if emotion_resonance else None
        if coordinate:
            emotional = []
            for mid, row in rows.items():
                if row['e_authored_by'] and row['valence'] is not None and row['arousal'] is not None:
                    distance = math.dist(coordinate, (row['valence'], row['arousal']))
                    if distance <= .65:
                        emotional.append((distance, -(row['e_initial_priority'] or 0), mid))
            channels['emotion'] = [mid for _, _, mid in sorted(emotional)[:2]]
        if spontaneous and not explicit:
            from .dream import select_association
            channels['perception'] = select_association(c, rows, session)
        # Raw sources remain evidence only. Auxiliary recall searches retained candidates.
        from .candidates import search as search_candidates
        candidate_hits = search_candidates(c, queries, pending, recent_ids, recent_text,
                                           allowed_scopes, allowed_sensitivity)
        scores, breakdown = fuse(searches, {k:v for k,v in channels.items() if k not in {'vector', 'fts'}},
                                 query_weights, channel_weights)
        ranked = sorted(scores, key=lambda mid: scores[mid], reverse=True)
        if store.reranker and ranked:
            try:
                result = store.reranker(query, [dict(rows[mid], base_score=scores[mid]) for mid in ranked[:20]], recent_messages=list(recent_messages)[-4:])
                if isinstance(result, dict):
                    result = result.get('ordered_ids', result)
                order = list(result) if isinstance(result, (dict, list, tuple)) else []
                ranked = list(dict.fromkeys([mid for mid in order if mid in scores] + ranked))
            except Exception:
                packet['degraded'].append('rerank_unavailable')
        fingerprints = set()
        from .dream import recall_page
        derived = recall_page(c, query, rows, pending, session, explicit)
        if derived and re.search(r'回顾|总结|反思|这周|本周|上周|这个月|本月|上月|季度|年度', query):
            packet['memories'].append(derived)
            if len(dumps(packet)) > budget - 32:
                packet['memories'].pop()
            else:
                derived = None
        for mid in ranked:
            if len(packet['memories']) >= limit:
                break
            row = rows[mid]
            digest = content_fingerprint(row['content'])
            if digest in fingerprints:
                continue
            hit_channels = list(breakdown[mid])
            association = set(hit_channels) <= {'graph', 'emotion', 'perception'}
            item = {'memory_id': mid, 'memory_kind': 'lmc', 'memory_subtype': row['category'],
                    'primary_scope': row['primary_scope'], 'title': row['title'], 'content': row['content'],
                    'occurred_at': row['occurred_start'], 'confidence': row['confidence'],
                    'recall_channels': hit_channels, 'recall_layer': 'association' if association else 'curated',
                    'evidence_role': 'association' if association else 'event_evidence',
                    'epistemic_label': 'recorded_experience' if row['primary_scope'] == 'self' else 'user_reported',
                    'source_experience_ids': [s['experience_id'] for s in source_map[mid]],
                    'source_times': source_times(source_map[mid]),
                    'usage_hint': '历史数据，当前表达优先；关联不证明因果，过去情绪不等于现在情绪。' + TIME_HINT}
            if row['status'] == 'superseded':
                item['epistemic_label'] = 'historical_fact'
                item['usage_hint'] = '这是已被新版本替代的历史事实，不是当前状态。'
            packet['memories'].append(item)
            if len(dumps(packet)) > budget - 32:
                packet['memories'].pop()
                continue
            fingerprints.add(digest)
            if len(packet['memories']) >= limit:
                break
        if derived and len(packet['memories']) < limit:
            packet['memories'].append(derived)
            if len(dumps(packet)) > budget - 32:
                packet['memories'].pop()
        selected_sources = {sid for item in packet['memories'] for sid in item['source_experience_ids']}
        fingerprints.update(content_fingerprint(item['content']) for item in packet['memories'])
        for _, candidate in candidate_hits:
            if len(packet['memories']) >= limit:
                break
            ids = json.loads(candidate['source_ids_json'])
            digest = content_fingerprint(candidate['content'])
            if digest in fingerprints or set(ids) & selected_sources:
                continue
            item = dict(memory_id=candidate['candidate_id'], memory_kind='candidate',
                        primary_scope=candidate['primary_scope'], title=candidate['title'],
                        content=candidate['content'], confidence=candidate['confidence'],
                        occurred_at=candidate['occurred_at'], source_experience_ids=ids,
                        source_times=source_times([dict(c.execute('SELECT * FROM raw_experiences WHERE experience_id=?', (sid,)).fetchone()) for sid in ids]),
                        recall_channels=['candidate'], recall_layer='auxiliary',
                        evidence_role='supporting_evidence', epistemic_label='extracted_candidate',
                        usage_hint='有原文依据的低重要性候选，仅作补充；正式记忆和当前表达优先。' + TIME_HINT)
            packet['memories'].append(item)
            if len(dumps(packet)) > budget - 32:
                packet['memories'].pop()
                continue
            fingerprints.add(digest)
            selected_sources.update(ids)
        trace.update(channels=channels, paths=paths, queries=queries, score_breakdown=breakdown)
    if store.relevance_model and packet['memories']:
        from .relevance import select
        candidates = packet['memories']
        try:
            selected, decisions = select(query, recent_messages, candidates, store.relevance_model,
                                         datetime.now(timezone(timedelta(hours=8))).isoformat())
            status = 'ok'
        except Exception as error:
            # Log known validation codes only; provider errors may contain private data.
            known_errors = {'empty_memory_relevance_response', 'invalid_memory_relevance_json',
                            'invalid_memory_relevance', 'invalid_memory_relevance_decision',
                            'invalid_memory_relevance_id'}
            error_code = str(error) if isinstance(error, ValueError) and str(error) in known_errors else type(error).__name__
            logging.getLogger(__name__).warning('Memory relevance selection failed (%s): %s', type(error).__name__, error_code)
            packet['degraded'].append('relevance_unavailable')
            selected, status = [], 'unavailable'
            decisions = [{'memory_id': m['memory_id'], 'decision': 'drop',
                          'reason': '相关性筛选异常，暂不注入未经确认的记忆'} for m in candidates]
        packet['memories'] = []
        for item in selected:
            if len(packet['memories']) >= output_limit:
                break
            packet['memories'].append(item)
            if len(dumps(packet)) > output_budget - 32:
                packet['memories'].pop()
        trace['relevance_filter'] = {'status': status, 'decisions': decisions}
        if status == 'unavailable':
            trace['relevance_filter']['error_code'] = error_code
        packet['relevance_filter'] = trace['relevance_filter']
    trace['selected_ids'] = [m['memory_id'] for m in packet['memories']]
    trace['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
    with store.connect(True) as c:
        # Two conversations may finish retrieval concurrently. Consume the
        # global association allowance under the write lock, only if offered.
        cooling = c.execute("SELECT 1 FROM lmc_dream_usage WHERE usage_kind='spontaneous_offered' AND created_at>=? LIMIT 1",
                            (utc(datetime.now(timezone.utc) - timedelta(hours=6)),)).fetchone()
        if cooling:
            kept = []
            for item in packet['memories']:
                channels = item.get('recall_channels', [])
                if 'perception' in channels:
                    channels.remove('perception')
                    if not channels:
                        continue
                kept.append(item)
            packet['memories'] = kept
            trace['selected_ids'] = [m['memory_id'] for m in kept]
        c.execute('INSERT OR REPLACE INTO lmc_recall_logs VALUES (?,?,?,?)',
                  (packet['request_id'], packet['query_intent'], dumps(trace), utc()))
        for item in packet['memories']:
            if item['memory_kind'] == 'candidate':
                continue
            from .dream import record_usage
            record_usage(c, packet['request_id'], item['memory_id'], 'context_selected', utc(), session)
            if 'perception' in item.get('recall_channels', []):
                c.execute('INSERT OR IGNORE INTO lmc_dream_usage VALUES (?,?,?,?,?)',
                          (packet['request_id'], item['memory_id'], session or '', 'spontaneous_offered', utc()))
            if session and item['memory_kind'] == 'lmc':
                c.execute('''INSERT INTO lmc_session_recall VALUES (?,?,?)
                    ON CONFLICT(session_id,memory_id) DO UPDATE SET recalled_at=excluded.recalled_at''',
                    (session, item['memory_id'], utc()))
    return packet
