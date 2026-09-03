import sys
from loguru import logger

from django_app.settings import env


def _resolve_log_level() -> str:
    """Resolve the stdlib root log level from DJANGO_LOG_LEVEL, falling back to WARNING on an invalid/missing value."""
    raw_level = env.str("DJANGO_LOG_LEVEL", "WARNING").upper()
    if raw_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
        logger.warning(
            "Ignoring invalid DJANGO_LOG_LEVEL={!r}; falling back to WARNING.",
            raw_level,
        )
        return "WARNING"
    return raw_level


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "loguru": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
        },
    },
    "root": {
        "handlers": ["loguru"],
        "level": _resolve_log_level(),
    },
    "loggers": {
        "litellm": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
        "LiteLLM": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
        "LiteLLM Router": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
        "LiteLLM Proxy": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
        "boto3": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
        "botocore": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
        "s3transfer": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
        "urllib3": {
            "handlers": ["loguru"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}