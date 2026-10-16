"""用可合并的通知唤醒单个记忆后台任务，实际待处理记录仍保存在数据库中。"""
from threading import Event, Lock


class MemoryWorkSignal:
    """合并队列类型，并在取走通知时原子清除信号。"""

    def __init__(self):
        self._event = Event()
        self._lock = Lock()
        self._queues = set()

    def notify(self, *queues):
        with self._lock:
            self._queues.update(queues)
            self._event.set()

    def take(self):
        with self._lock:
            queues = self._queues
            self._queues = set()
            self._event.clear()
            return queues

    def set(self):
        self.notify('chat', 'call', 'extraction')

    def clear(self):
        self.take()

    def is_set(self):
        return self._event.is_set()

    def wait(self, timeout=None):
        return self._event.wait(timeout)


memory_work_available = MemoryWorkSignal()


def notify_after_commit(connection, queue):
    """只登记通知，由支持提交通知的连接在事务成功提交后发送。"""
    register = getattr(connection, 'mark_memory_work', None)
    if register is not None:
        register(queue)
