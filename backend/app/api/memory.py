"""HTTP endpoints for inspecting and administering the memory subsystem."""
from collections.abc import Callable

from fastapi import APIRouter, HTTPException


def build_memory_router(memory_store, current_thread: Callable[[], str | None]) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    def home():
        return {"message": "Libra Companion backend is running", "thread_id": current_thread()}

    @router.get("/memory/status")
    def memory_status():
        from domains.memory.context import features
        return {**memory_store.inspect(), "features": features(memory_store)}

    @router.get("/memory/health")
    def memory_health():
        return memory_store.health()

    @router.get("/memory/calendar")
    def memory_calendar(level: str | None = None, limit: int = 50):
        from domains.memory.dream import inspect
        try:
            return inspect(memory_store, level=level, limit=limit)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/memory/dream")
    def dream_status():
        from domains.memory.dream import inspect
        return inspect(memory_store)

    @router.get('/memory/reading')
    def memory_reading(kind: str = 'reviews', offset: int = 0, limit: int = 30, date: str | None = None, level: str | None = None):
        from domains.memory.dream_journal import reading
        try:
            return reading(memory_store, kind=kind, offset=offset, limit=limit, on_date=date, level=level)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/memory/dream")
    def request_dream():
        from domains.memory.dream import request
        return request(memory_store)

    @router.get("/memory/quality-audit")
    def memory_quality_audit(limit: int = 500):
        return memory_store.quality_audit(limit)

    @router.post("/memory/backups")
    def create_memory_backup():
        try:
            return memory_store.create_backup()
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @router.patch("/memory/features")
    def configure_memory_features(values: dict):
        from domains.memory.context import set_features
        try:
            return set_features(memory_store, values)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/memory/records/{memory_id}")
    def memory_detail(memory_id: str):
        result = memory_store.detail(memory_id)
        if result is None:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return result

    @router.get("/memory/timeline")
    def memory_timeline(story_memory_id: str | None = None, limit: int = 100):
        from domains.memory.context import timeline
        return timeline(memory_store, story_memory_id, limit)

    @router.post("/memory/jobs/{job_id}/retry")
    def retry_memory_job(job_id: str):
        if not memory_store.retry_failed(job_id):
            raise HTTPException(status_code=409, detail="任务不存在或无需手动重试")
        return {"success": True}

    @router.post("/memory/records/{memory_id}/invalidate")
    def invalidate_memory(memory_id: str):
        if not memory_store.invalidate(memory_id):
            raise HTTPException(status_code=404, detail="记忆不存在或已失效")
        return {"success": True}

    return router
