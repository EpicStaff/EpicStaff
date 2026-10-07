import asyncio
import contextlib
import sys

import uvicorn
from app.core.settings import settings
from app.main import create_app
from loguru import logger


def uvicorn_log_level(level: str) -> str:
    """Translate a validated loguru level name to uvicorn's; uvicorn has no SUCCESS level."""
    return "info" if level == "SUCCESS" else level.lower()


async def main():
    logger.remove()
    logger.add(sys.stderr, level=settings.LOG_LEVEL)

    app = create_app()

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.WEBHOOK_PORT,
        log_level=uvicorn_log_level(settings.LOG_LEVEL),
    )
    server = uvicorn.Server(config)

    logger.info("Starting Uvicorn server...")
    await server.serve()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
