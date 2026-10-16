"""Durable segment extraction leases and retry; candidate writes belong to LMC."""
from .base import *


class MemoryExtractionMixin:
    def claim_job(self, now=None):
        now = utc(now)
        with self.connect(True) as c:
            job = c.execute('''SELECT * FROM memory_jobs WHERE job_kind='lmc' AND (
                (job_status IN ('pending','retryable') AND next_attempt_at<=?) OR
                (job_status='processing' AND lease_until<=?))
                ORDER BY created_at LIMIT 1''', (now, now)).fetchone()
            if not job:
                return None
            token = uid('lease')
            until = utc(datetime.fromisoformat(now) + timedelta(minutes=10))
            c.execute("UPDATE memory_jobs SET job_status='processing',attempts=attempts+1,lease_token=?,lease_until=?,updated_at=? WHERE job_id=?",
                      (token, until, now, job['job_id']))
            return dict(c.execute('SELECT * FROM memory_jobs WHERE job_id=?', (job['job_id'],)).fetchone())
    def fail_job(self, job, error):
        now = utc()
        code = str(error) if isinstance(error, ValidationError) else type(error).__name__
        # 只记录受限的错误代码，不记录模型输出、凭据或原始文本。
        code = re.sub('[^a-zA-Z0-9_]', '', code)[:80]
        with self.connect(True) as c:
            c.execute('''UPDATE memory_jobs SET job_status=?,error_code=?,lease_token=NULL,lease_until=NULL,
                next_attempt_at=?,updated_at=? WHERE job_id=? AND lease_token=? AND job_status='processing' ''',
                ('failed' if job['attempts']>=5 else 'retryable',code,
                 utc(datetime.fromisoformat(now)+timedelta(seconds=min(1800,30*2**min(job['attempts'],6)))),
                 now,job['job_id'],job['lease_token']))
    def retry_failed(self, job_id):
        with self.connect(True) as c:
            return c.execute("UPDATE memory_jobs SET job_status='retryable',attempts=0,next_attempt_at=?,updated_at=? WHERE job_id=? AND job_status='failed' AND job_kind='lmc'", (utc(),utc(),job_id)).rowcount == 1
