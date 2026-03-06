import uvicorn
from loguru import logger
from core.config import settings


def main():
    if settings.REALTIME_DEBUG_MODE:
        logger.info("RUNNING IN DEBUG MODE")

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=settings.REALTIME_PORT,
        reload=settings.REALTIME_RELOAD,
        reload_dirs=["."] if settings.REALTIME_RELOAD else None,
        workers=settings.REALTIME_WORKERS,
        log_level="debug" if settings.REALTIME_DEBUG_MODE else "info",
    )


if __name__ == "__main__":
    main()
