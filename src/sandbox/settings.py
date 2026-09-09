from pathlib import Path

from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / '../.env')

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.str("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")

CODE_RESULT_CHANNEL = env.str("CODE_RESULT_CHANNEL")
STORAGE_MUTATION_CHANNEL = env.str("STORAGE_MUTATION_CHANNEL")
CODE_EXEC_CHANNEL = env.str("CODE_EXEC_CHANNEL")

OUTPUT_PATH = env.path("SANDBOX_OUTPUT_PATH")
BASE_VENV_PATH = env.path("SANDBOX_BASE_VENV_PATH")

STORAGE_HOST = env.str("MINIO_HOST")
STORAGE_PORT = env.str("MINIO_PORT")
http = "https" if env.bool("MINIO_SSL") else "http"
STORAGE_ENDPOINT = f"{http}://{STORAGE_HOST}:{STORAGE_PORT}"
STORAGE_ACCESS_KEY = env.str("MINIO_USER")
STORAGE_SECRET_KEY = env.str("MINIO_PASSWORD")
STORAGE_BUCKET_NAME = env.str("MINIO_BUCKET")

MASK_SECRET = env.bool("SANDBOX_MASK_SECRET")
