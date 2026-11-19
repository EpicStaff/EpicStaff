from common.bootstrap.logging import configure_logging
from foundation.utils.litestar import di, error_handler, lifespan
from litestar import Litestar
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import (
    RapidocRenderPlugin,
    ScalarRenderPlugin,
    StoplightRenderPlugin,
    SwaggerRenderPlugin,
)

import manager.bootstrap
import manager.bootstrap.runtime  # noqa: F401  registers the manager's runtime (queues + runners)
from manager import settings
from manager.presentation.rest import controllers
from manager.presentation.rest.worker_controller import WorkerController

configure_logging()

app = Litestar(
    debug=settings.DEBUG,
    route_handlers=[
        controllers.VenvController,
        controllers.ExecutionController,
        controllers.CustomLibraryController,
        controllers.WheelController,
        WorkerController,
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
