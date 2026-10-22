"""Detects whether graphrag can run on this host without importing graphrag.

The graphrag library crashes with SIGILL on CPUs that lack AVX2. This module reads
the CPU flags so the service can disable graphrag gracefully instead of crashing.
"""

_CPUINFO_PATH = "/proc/cpuinfo"
_REQUIRED_FLAG = "avx2"

_available: bool | None = None


def detect_graphrag_availability() -> bool:
    """Determine (once) whether graphrag can run here and cache the result.

    Returns True when the CPU exposes the AVX2 flag or when x86 CPU flags cannot be read
    (fail open, which includes every ARM host). Returns False only when x86 flags are
    readable and AVX2 is absent.
    """
    global _available
    flags = _read_cpu_flags()
    _available = flags is None or _REQUIRED_FLAG in flags
    return _available


def is_graphrag_available() -> bool:
    """Return the cached availability, detecting it on first call."""
    if _available is None:
        return detect_graphrag_availability()
    return _available


def _read_cpu_flags() -> set[str] | None:
    try:
        with open(_CPUINFO_PATH, encoding="utf-8") as cpuinfo:
            lines = cpuinfo.readlines()
    except OSError:
        return None

    # AVX2 is an x86 flag, listed on the x86 `flags` line. ARM kernels list a `Features`
    # line instead, and so does an amd64 container emulated on an Apple-silicon Mac, so
    # a missing `flags` line means "not an x86 CPU view" and is treated as unknown.
    # ponytail: an emulator without AVX2 is let through and graphrag may SIGILL there;
    # probe-importing graphrag in a subprocess would detect that.
    flags: set[str] = set()
    for line in lines:
        key = line.split(":", 1)[0].strip().lower()
        if key == "flags":
            flags.update(line.split(":", 1)[1].split())
    return flags or None
