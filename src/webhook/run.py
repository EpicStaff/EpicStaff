import asyncio
import uvicorn
from app.core.settings import settings
from app.main import create_app
from loguru import logger

async def main():
    app = create_app()
    
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=settings.WEBHOOK_PORT,
        log_level=settings.LOG_LEVEL.lower()
    )
    server = uvicorn.Server(config)

    logger.info("Starting Uvicorn server...")
    await server.serve()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass