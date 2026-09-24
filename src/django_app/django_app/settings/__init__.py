from contextlib import suppress
from pathlib import Path

from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parents[2]

env = Env()

if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / "../.env")


from .base import *
from .audit import *
from .caches import *
from .communication import *
from .cors import *
from .database import *
from .email import *
from .jwt import *
from .logging import *
from .redis import *
from .rest_framework import *
from .spectacular import *
from .storage import *
from .templates import *
from .webhook import *

with suppress(ImportError):
    from .local import *
