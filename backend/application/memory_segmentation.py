"""后台按顺序读取尚未判断的新消息，每次交一条给记忆模块处理。"""
from domains.memory.store import ValidationError, utc


def drain_segments(store, *, queue=None, now=None, force=False, model=None):
    """每类最多消费二百条；失败只暂缓对应消息流，下轮从原始记录重试。"""
    if queue not in (None, 'chat', 'call'):
        raise ValidationError('invalid_segmentation_queue')
    now = utc(now)
    with store.connect(True) as c:
        store._apply_stream_boundaries(c, now, queue)
        chat = store._pending_rows(c, 'chat') if queue in (None, 'chat') else []
        calls = store._pending_rows(c, 'call') if queue in (None, 'call') else []
    blocked = set()
    processed = 0
    for raw in chat + calls:
        stream = store._stream_key(raw)
        if stream in blocked:
            continue
        try:
            result = store.segment_pending(raw, queue=queue, now=now, force=force, model=model)
        except Exception:
            blocked.add(stream)
            continue
        if result == 'stale':
            blocked.add(stream)
        elif result == 'saved':
            processed += 1
    store._finish_segmentation(queue, now, force)
    return processed
