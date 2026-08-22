from loguru import logger

CPUINFO_PATH = "/proc/cpuinfo"


def supports_avx2() -> bool:
    """
    Check whether the host CPU advertises AVX2 support via /proc/cpuinfo.

    Defaults to True (fail open) if the file can't be read or parsed, e.g.
    on non-Linux dev environments. This check must never import `lancedb`
    or `graphrag` — it exists specifically to be safe to call before those
    modules are touched.
    """
    try:
        with open(CPUINFO_PATH, "r") as cpuinfo_file:
            for line in cpuinfo_file:
                if line.startswith("flags"):
                    return "avx2" in line.split(":", 1)[1].split()

        return False
    except Exception as e:
        logger.warning("Could not determine AVX2 support, defaulting to True: {}", e)
        return True
