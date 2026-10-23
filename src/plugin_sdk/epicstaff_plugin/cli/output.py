"""Exit codes and output shared by every command."""

import sys
from collections.abc import Iterable

from epicstaff_plugin.problems import Problem

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


class UsageError(Exception):
    """The command was called wrongly: a missing file, an existing output, a bad key."""


def print_problems(problems: Iterable[Problem]) -> None:
    for problem in problems:
        print(f"{problem.loc}: {problem.message}")


def print_error(message: str) -> None:
    print(f"epicstaff-plugin: error: {message}", file=sys.stderr)
