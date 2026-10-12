"""Periodic glibc ``malloc_trim`` for the long-lived django_app processes.

CPython frees large payloads back to glibc, but glibc keeps the pages in its arenas,
so RSS only grows. Each process (the web server, ``listen_redis`` and ``cache_redis``)
starts its own trim thread; the thread does not survive a fork.
"""

import ctypes
import os
import threading
import time

from django.conf import settings
from loguru import logger

try:
    _libc = ctypes.CDLL("libc.so.6")
except OSError:
    _libc = None

_trim_thread_lock = threading.Lock()
_trim_thread: threading.Thread | None = None


def read_rss_mb() -> float:
    """Return this process's resident set size in MB, or -1.0 where /proc is unavailable."""
    try:
        with open(f"/proc/{os.getpid()}/status") as status_file:
            for line in status_file:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError):
        return -1.0
    return -1.0


def malloc_trim_and_log() -> None:
    """Return free glibc heap pages to the OS and log the resulting RSS; no-op without glibc."""
    if _libc is None:
        return

    try:
        _libc.malloc_trim(0)
        logger.info("After malloc_trim(0): rss={:.1f}MB", read_rss_mb())
    except Exception as error:
        logger.warning("malloc_trim failed: {}", error)


def _run_periodic_malloc_trim(interval: float) -> None:
    logger.info("Periodic malloc_trim thread started (interval={}s)", interval)
    while True:
        time.sleep(interval)
        malloc_trim_and_log()


def start_periodic_malloc_trim() -> None:
    """Start this process's background malloc_trim thread unless one is already running.

    Safe to call on every request or worker start. The thread is a daemon, so it never
    blocks process exit, and it runs ``malloc_trim`` every ``settings.MALLOC_TRIM_INTERVAL``
    seconds. Nothing starts when the interval is set to ``none`` or glibc is unavailable.
    """
    global _trim_thread

    interval = settings.MALLOC_TRIM_INTERVAL
    if interval is None or _libc is None:
        return

    with _trim_thread_lock:
        # A thread object inherited through fork is not alive in the child, so it restarts.
        if _trim_thread is not None and _trim_thread.is_alive():
            return
        _trim_thread = threading.Thread(
            target=_run_periodic_malloc_trim,
            args=(interval,),
            name="malloc-trim",
            daemon=True,
        )
        _trim_thread.start()
