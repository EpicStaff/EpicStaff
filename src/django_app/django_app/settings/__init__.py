from contextlib import suppress
from pathlib import Path

from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parents[2]

env = Env()

if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / "../.env")


# NOTE: import order below is NOT alphabetical and must stay that way.
# `.caches` and `.communication` do `from django_app.settings import REDIS_HOST, ...`
# (a self-import back into this partially-built package), so `.redis` — which
# defines those names — must run before them. Do not let ruff/isort re-sort
# this block back to alphabetical order (see EST-4077 boot crash / ImportError).
from .base import *  # noqa: F403
from .redis import *  # noqa: F403
from .caches import *  # noqa: F403
from .communication import *  # noqa: F403
from .cors import *  # noqa: F403
from .database import *  # noqa: F403
from .email import *  # noqa: F403
from .jwt import *  # noqa: F403
from .logging import *  # noqa: F403
from .rest_framework import *  # noqa: F403
from .spectacular import *  # noqa: F403
from .storage import *  # noqa: F403
from .templates import *  # noqa: F403
from .webhook import *  # noqa: F403

with suppress(ImportError):
    from .local import *
