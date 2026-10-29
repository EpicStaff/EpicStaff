from typing import Literal

type LibraryString = str
# Why a job never reached the worker; reported as the outcome of its BENCH checkpoint.
type NotRunReason = Literal["venv_failed", "dispatch_failed"]
