"""Bind content-domain adapters to the same execution boundary used by chat.

Selection stays with the caller. No global mutable executor or accumulated
receipts: each call emits the standard metadata-only execution receipt.
"""
from application.tool_contracts import TOOL_SPECS
from application.tool_execution import ToolExecutor


def execute(name, handler, *, source, **arguments):
    executor = ToolExecutor({TOOL_SPECS[name].adapter: handler}, source=source)
    return executor.call(name, **arguments).unwrap()
