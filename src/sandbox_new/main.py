import common.bootstrap  # noqa: F401  registers the cross-service runtime (queues + runners)
import manager.bootstrap  # noqa: F401  registers dependencies and lifespan hooks
import settings
from foundation.utils.litestar import di, error_handler, lifespan
from litestar import Litestar
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import (
    RapidocRenderPlugin,
    ScalarRenderPlugin,
    StoplightRenderPlugin,
    SwaggerRenderPlugin,
)
from manager.presentation.rest.controllers import ExecutionController, VenvController

app = Litestar(
    debug=settings.DEBUG,
    route_handlers=[
        VenvController,
        ExecutionController,
    ],
    on_startup=lifespan.get_startups(),
    on_shutdown=lifespan.get_shutdowns(),
    dependencies=di.get_dependencies(),
    exception_handlers=error_handler.get_handlers(),
    openapi_config=OpenAPIConfig(
        title="Sandbox API",
        version="1.0.0",
        render_plugins=[
            ScalarRenderPlugin(),
            RapidocRenderPlugin(),
            StoplightRenderPlugin(),
            SwaggerRenderPlugin(),
        ],
    ),
)
