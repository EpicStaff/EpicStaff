"""The Weather backend: a FastAPI app the EpicStaff node serves behind its gateway.

The node runs it with `python -m epicstaff_plugin.serve`, which checks the gateway context
of every request before it reaches a route here; `context_from_scope` returns that context.
"""

from typing import Any

from epicstaff_plugin.gateway import context_from_scope
from epicstaff_plugin.runtime import runtime_config
from fastapi import FastAPI, Request

# No generated API pages: the public address serves only the routes below.
app = FastAPI(title="Weather", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/ping")
async def ping(request: Request) -> dict[str, str]:
    """A public path (see the manifest): reachable without logging in to EpicStaff."""
    return {"status": "ok", "mode": context_from_scope(request.scope).mode}


@app.get("/api/whoami")
async def whoami(request: Request) -> dict[str, Any]:
    """The context EpicStaff sent with this request: who is asking, from which organization."""
    return context_from_scope(request.scope).model_dump(mode="json")


@app.get("/api/settings")
async def settings() -> dict[str, Any]:
    """The deployment's settings this backend uses; secret ones are never returned."""
    return {"units": runtime_config().setting("units")}
