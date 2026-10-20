import httpx
from bootstrap.di import get_dependencies
from bootstrap.lifespans import get_lifespans
from common.logging import configure_logging
from litestar import Litestar
from litestar.config.cors import CORSConfig
from litestar.datastructures import State
from litestar.openapi import OpenAPIConfig
from presentation.rest.controllers.health import HealthController
from presentation.rest.controllers.internal import InternalController
from presentation.rest.controllers.operator import InboxStreamController, OperatorController
from presentation.rest.controllers.public import PublicController
from presentation.rest.error_handlers import get_error_handlers
from settings import Settings, load_settings


def create_app(
    settings: Settings | None = None,
    *,
    django_transport: httpx.AsyncBaseTransport | None = None,
    redis_client=None,
) -> Litestar:
    """Build the app; tests pass a fake Django transport and a fake Redis."""
    settings = settings or load_settings()
    configure_logging(settings.CHAT_LOG_LEVEL)
    return Litestar(
        debug=False,  # Litestar debug logs every 4xx as ERROR and leaks tracebacks; error_handlers logs real 500s
        route_handlers=[
            HealthController,
            InboxStreamController,
            InternalController,
            OperatorController,
            PublicController,
        ],
        on_startup=get_lifespans("on_startup"),
        on_shutdown=get_lifespans("on_shutdown"),
        dependencies=get_dependencies(),
        exception_handlers=get_error_handlers(),
        # Preflight cannot know the binding (the public key is in the body); the handlers
        # enforce allowed_origins on the real request. Tokens are bearer headers, not cookies.
        cors_config=CORSConfig(
            allow_origins=["*"],
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "Last-Event-ID"],
        ),
        state=State(
            {"settings": settings, "django_transport": django_transport, "redis": redis_client}
        ),
        openapi_config=OpenAPIConfig(title="Chat API", version="1.1.0", path="/chat/schema"),
    )


app = create_app()
