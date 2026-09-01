from contextlib import suppress
import environ
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
env.read_env(env_file=BASE_DIR / '../.env')


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
    from .local import *  # noqa: F403