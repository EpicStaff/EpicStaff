"""Escape hatch for running without Landlock confinement.

Kept separate from the Landlock binding itself so this override -- a
deliberately temporary, security-relevant knob -- can be reviewed and
deleted independently of the binding it sits next to.
"""

import os

REQUIRE_ISOLATION_ENV_VAR = "SANDBOX_REQUIRE_ISOLATION"

_DISABLING_VALUES = frozenset({"false", "0", "no", "off", "f", "n"})


def isolation_required() -> bool:
    """Whether execution must refuse to run when Landlock is unavailable.

    Reads the environment on each call, matching `secret_scrubber.masking_enabled()`:
    the setting is a property of the running configuration, not of module load order.
    Defaults to True -- fail closed.
    """
    raw = os.environ.get(REQUIRE_ISOLATION_ENV_VAR)
    if raw is None:
        return True
    return raw.strip().lower() not in _DISABLING_VALUES
