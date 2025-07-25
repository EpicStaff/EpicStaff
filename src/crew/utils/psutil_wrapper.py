import time
from functools import wraps
import os
import psutil

def psutil_wrapper(func):
    """
    A decorator to wrap a function with psutil functionality.
    Measures memory usage and execution time.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss  # Resident Set Size in bytes
        time_start = time.perf_counter()

        result = func(*args, **kwargs)

        time_end = time.perf_counter()
        mem_after = process.memory_info().rss

        print(f"[{func.__name__}] Memory before: {mem_before / 1024:.2f} KB")
        print(f"[{func.__name__}] Memory after: {mem_after / 1024:.2f} KB")
        print(f"[{func.__name__}] Memory delta: {(mem_after - mem_before) / 1024:.2f} KB")
        print(f"[{func.__name__}] Execution time: {time_end - time_start:.4f} seconds")
        print("="*40)

        return result

    return wrapper