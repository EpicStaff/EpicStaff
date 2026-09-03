import uvicorn
from loguru import logger
from core import config


def main():
    if config.REALTIME_DEBUG_MODE:
        logger.info("RUNNING IN DEBUG MODE")

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=config.REALTIME_PORT,
        reload=config.REALTIME_RELOAD,
        reload_dirs=["."] if config.REALTIME_RELOAD else None,
        workers=config.REALTIME_WORKERS,
        log_level="debug" if config.REALTIME_DEBUG_MODE else "info",
    )


if __name__ == "__main__":
    main()
