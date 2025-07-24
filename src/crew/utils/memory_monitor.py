import os
import sys
import gc
import psutil
import tracemalloc
from collections import defaultdict
from loguru import logger
from utils.singleton_meta import SingletonMeta


class MemoryMonitor(metaclass=SingletonMeta):
    def __init__(self):
        self.start = None
        self.last_change = None
        self.previous_object_ids = set()
        self.previous_snapshot = None

        tracemalloc.start(25)  # Keep stack trace of up to 25 frames

    def log_memory_usage(self):
        process = psutil.Process(os.getpid())
        mem = process.memory_info().rss

        if self.start is None:
            self.start = mem
            self.last_change = mem
            # self.previous_snapshot = tracemalloc.take_snapshot()
        else:
            if self.last_change != mem:
                delta = (mem - self.last_change) / 1024
                logger.critical(f"Memory Delta from last change: {delta:.2f} KB")
                self.last_change = mem
                # self._log_tracemalloc_deltas()
                pass

    def _log_tracemalloc_deltas(self, limit=5):
        snapshot = tracemalloc.take_snapshot()
        if self.previous_snapshot is None:
            self.previous_snapshot = snapshot
            return

        stats_diff = snapshot.compare_to(self.previous_snapshot, 'traceback')
        self.previous_snapshot = snapshot

        if stats_diff:
            logger.info("Top memory allocation deltas:")
            for stat in stats_diff[:limit]:
                logger.info(f"{stat.size_diff / 1024:.2f} KB in {stat.count_diff} blocks")
                for line in stat.traceback.format()[-3:]:
                    logger.info(line)
        else:
            logger.info("No allocation deltas detected by tracemalloc.")
        pass
    

class MemoryMonitorContext:
    def __init__(self, label: str = ""):
        self.label = label
        self.start_mem = None
        self.last_mem = None
        self.start_snapshot = None

    def __enter__(self):
        logger.info(f"Entering memory monitoring context: {self.label}")
        tracemalloc.start(25)  # Store up to 25 frames in traceback
        #gc.collect()

        self.start_mem = psutil.Process(os.getpid()).memory_info().rss
        self.last_mem = self.start_mem
        self.start_snapshot = tracemalloc.take_snapshot()
        logger.info(f"Start memory: {self.start_mem / 1024:.2f} KB")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        #gc.collect()
        end_mem = psutil.Process(os.getpid()).memory_info().rss
        delta = (end_mem - self.last_mem) / 1024
        total_delta = (end_mem - self.start_mem) / 1024
        logger.critical(f"[{self.label}] Final memory: {end_mem / 1024:.2f} KB")
        logger.critical(f"[{self.label}] Memory delta since enter: {total_delta:.2f} KB")
        logger.critical(f"[{self.label}] Memory delta since last log: {delta:.2f} KB")

        self._log_tracemalloc_deltas()
        tracemalloc.stop()
        logger.info(f"Exiting memory monitoring context: {self.label}")

    def _log_tracemalloc_deltas(self, limit=5):
        end_snapshot = tracemalloc.take_snapshot()
        stats_diff = end_snapshot.compare_to(self.start_snapshot, 'traceback')

        if stats_diff:
            logger.info("Top memory allocation deltas:")
            for stat in stats_diff[:limit]:
                logger.info(f"{stat.size_diff / 1024:.2f} KB in {stat.count_diff} blocks")
                for line in stat.traceback.format()[-3:]:
                    logger.info(line)
        else:
            logger.info("No allocation deltas detected by tracemalloc.")
