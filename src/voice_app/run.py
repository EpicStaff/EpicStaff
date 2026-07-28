import uvicorn
import sys
from loguru import logger
from app.core.settings import settings
import dotenv

dotenv.load_dotenv()


def start_tunnel():
    # pyngrok is a dev-only dependency (local tunneling for testing against
    # Twilio webhooks) and is not installed in production. Import it lazily
    # so this module can still be imported when pyngrok is absent.
    try:
        from pyngrok import ngrok
    except ImportError:
        logger.error(
            "pyngrok is not installed. Install the 'dev' dependency group "
            "(`poetry install --with dev`) to use start_tunnel() locally."
        )
        return

    try:
        ngrok.set_auth_token(settings.WEBHOOK_TOKEN)
        public_url = ngrok.connect(settings.PORT).public_url
        logger.info(f"Ngrok tunnel established: {public_url}")

    except Exception as e:
        logger.error(f"Failed to start ngrok: {e}")


def main():
    if not any(arg in sys.argv for arg in ["--reload", "reload"]):
        start_tunnel()

    uvicorn.run(
        "app.main:app", host=settings.HOST, port=settings.PORT, log_level="info"
    )


if __name__ == "__main__":
    main()
