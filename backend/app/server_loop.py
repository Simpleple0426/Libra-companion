"""Network loop for the Windows desktop backend.

The Proactor accept loop can stop listening after WinError 64 on a dropped
network connection. This service uses synchronous subprocess management, so
the selector loop is sufficient for its HTTP server.
"""
import asyncio


def create_loop():
    return asyncio.SelectorEventLoop()
