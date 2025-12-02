from typing import Optional
from app.providers.base import AbstractTunnelProvider
from fastapi import FastAPI
from app.controllers import webhook_routes
from app.services.redis_service import close_redis_connection
from app.services.webhook_service import WebhookService
from fastapi.middleware.cors import CORSMiddleware


def create_app(webhook_service: Optional[WebhookService] = None) -> FastAPI:
    """
    Factory function to create and configure the FastAPI app.
    """
    app = FastAPI(title="WebhookService")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # It's a webhook service so I don't care
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhook_routes.router)

    @app.get("/api/tunnel-url")
    async def get_tunnel_url():
        tunnel_url = await webhook_service.get_tunnel_url()

        if tunnel_url is not None:
            return {
                "status": "success",
                "tunnel_url": tunnel_url,
            }
        description: str = ""
        if webhook_service.tunnel is None:
            description = "No tunnel available"
        response = {"status": "fail"}
        if description:
            response["description"] = description
        return response

    @app.on_event("shutdown")
    async def shutdown_event():
        print("Application shutting down...")
        await close_redis_connection()

    return app
