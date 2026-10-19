from litestar import Controller, get, status_codes


class HealthController(Controller):
    path = "/chat"
    tags = ("Maintenance",)

    @get(
        path="/health",
        status_code=status_codes.HTTP_200_OK,
        summary="Liveness for compose and nginx",
    )
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}
