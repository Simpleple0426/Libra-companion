"""Self-contained browser console for inspecting persisted cognition turns."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


_CONSOLE = Path(__file__).with_name("trace_console.html")


def build_trace_router() -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/debug/trace", response_class=HTMLResponse)
    def trace_console():
        return HTMLResponse(_CONSOLE.read_text(encoding="utf-8"))

    return router
