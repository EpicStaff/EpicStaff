from litestar import Controller, get, status_codes


class MaintenanceController(Controller):
    path = ""
    tags = ("Maintenance",)

    @get(path="healthy/", status_code=status_codes.HTTP_200_OK, summary="Health check")
    async def healthy(self) -> dict[str, str]:
        return {"status": "ok"}
