from collections.abc import Iterable

from django.conf import settings
from foundation.transport.http import Client


class SandboxVenvClient(Client):
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        super().__init__(
            base_url=base_url or f"http://{settings.SANDBOX_HOST}:{settings.SANDBOX_PORT}",
            timeout=timeout if timeout is not None else settings.SANDBOX_CLIENT_TIMEOUT,
        )

    def list(
        self,
        *,
        ids: Iterable[str],
        limit: str | None = None,
        offset: str | None = None,
    ) -> dict:
        ids = list(ids)
        if not ids:
            return {
                "count": 0,
                "limit": int(limit) if limit is not None else 0,
                "offset": int(offset) if offset is not None else 0,
                "next": None,
                "previous": None,
                "result": [],
            }
        params: dict = {"ids": ids}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        response = self.get(url="/venvs", params=params)
        return response.json()

    def retrieve(self, venv_id: str) -> dict:
        response = self.get(url=f"/venvs/{venv_id}")
        return response.json()

    def create(self, data: dict) -> dict:
        response = self.post(url="/venvs", json=data)
        return response.json()

    def update(self, venv_id: str, data: dict) -> dict:
        response = self.patch(url=f"/venvs/{venv_id}", json=data)
        return response.json()

    def remove(self, venv_id: str) -> None:
        self.delete(url=f"/venvs/{venv_id}")
