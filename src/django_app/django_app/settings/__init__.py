from contextlib import suppress
from pathlib import Path

from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parents[2]

env = Env()

# docker-compose.yaml sets it for every service; a process on the host reads src/.env instead.
RUN_IN_DOCKER = env.bool("RUN_IN_DOCKER", False)

if not RUN_IN_DOCKER:
    env.read_env(env_file=BASE_DIR / "../.env")


from .audit import *
from .base import *
from .caches import *
from .communication import *
from .cors import *
from .database import *
from .email import *
from .execution_timeout import *
from .jwt import *
from .logging import *
from .plugins import *
from .redis import *
from .rest_framework import *
from .sandbox import *
from .spectacular import *
from .storage import *
from .templates import *
from .webhook import *

with suppress(ImportError):
    from .local import *
