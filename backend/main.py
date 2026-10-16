"""Stable ASGI compatibility alias for app.runtime.

Keep ``uvicorn main:app`` and existing imports working while the implementation
lives in the layered application package.
"""
from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module("app.runtime")
