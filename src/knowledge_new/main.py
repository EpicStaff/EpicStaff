from bootstrap.di import get_dependencies
from bootstrap.lifespans import get_lifespans
from litestar import Litestar
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import (
    RapidocRenderPlugin,
    ScalarRenderPlugin,
    StoplightRenderPlugin,
    SwaggerRenderPlugin,
)
from presentation.rest.controllers.maintenances import MaintenanceController
from presentation.rest.controllers.rag import RagController
from presentation.rest.error_handlers import get_error_handlers
from settings import settings

app = Litestar(
    debug=settings.DEBUG,
    route_handlers=[
        MaintenanceController,
        RagController,
    ],
    on_startup=get_lifespans("on_startup"),
    on_shutdown=get_lifespans("on_shutdown"),
    dependencies=get_dependencies(),
    exception_handlers=get_error_handlers(),
    openapi_config=OpenAPIConfig(
        title="Knowledge API",
        version="1.0.0",
        render_plugins=[
            ScalarRenderPlugin(),
            RapidocRenderPlugin(),
            StoplightRenderPlugin(),
            SwaggerRenderPlugin(),
        ],
    ),
)
