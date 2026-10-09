"""Named durations collected during the run, written to timings.json at session end."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("e2e.timings")


class Timings:
    """Named durations collected during the run, written to timings.json at session end."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.measurements: dict[str, float] = {}

    def record(self, name: str, seconds: float) -> None:
        self.measurements[name] = round(seconds, 2)
        logger.info("timing %s = %.2fs", name, seconds)

    def write(self) -> Path:
        report: dict[str, float] = {}
        stack_ready_file = self.directory / "stack_ready.json"
        if stack_ready_file.exists():
            report.update(json.loads(stack_ready_file.read_text()))
        report.update(self.measurements)
        self.directory.mkdir(parents=True, exist_ok=True)
        timings_file = self.directory / "timings.json"
        timings_file.write_text(json.dumps(report, indent=2, sort_keys=True))
        return timings_file
