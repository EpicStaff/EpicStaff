from math import log
import uvicorn
import sys
from dotenv import load_dotenv, find_dotenv
from loguru import logger
if "--debug" in sys.argv:
    logger.info("RUNNING IN DEBUG MODE")

    load_dotenv(find_dotenv("debug.env"))
else:
    load_dotenv(find_dotenv(".env"))



def main():
    """Run the FastAPI server with uvicorn."""
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8050,
        reload=False,
        reload_dirs=["src"],
        workers=1,
        log_level="debug",
    )


if __name__ == "__main__":
    main()
