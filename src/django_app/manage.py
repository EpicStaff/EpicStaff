#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

from loguru import logger


def main():
    """Run administrative tasks."""
    # utils.logger installs the real sink only once a view or service is imported,
    # so an error during django.setup() would otherwise reach loguru's default
    # handler, whose `diagnose` prints local variable values such as secrets.
    logger.remove()
    logger.add(sys.stderr, diagnose=False)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    try:
        execute_from_command_line(sys.argv)
    except Exception as e:
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
