from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from foundation.transport.http import Client


class SandboxClient(Client):
    """Where the sandbox service is and how long it may take to answer."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        super().__init__(
            base_url=base_url or f"http://{settings.SANDBOX_HOST}:{settings.SANDBOX_PORT}",
            timeout=timeout if timeout is not None else settings.SANDBOX_CLIENT_TIMEOUT,
        )

    @staticmethod
    def empty_page(limit: str | None, offset: str | None) -> dict:
        """The page a caller gets when it asks for no ids at all.

        Answered here rather than upstream because a query string drops an empty
        list: `ids=[]` would arrive as no filter at all and return every
        organization's rows.
        """
        return {
            "count": 0,
            "limit": int(limit) if limit is not None else 0,
            "offset": int(offset) if offset is not None else 0,
            "next": None,
            "previous": None,
            "result": [],
        }


class SandboxVenvClient(SandboxClient):
    def list(
        self,
        *,
        ids: Iterable[str],
        search: str | None = None,
        order: str | None = None,
        limit: str | None = None,
        offset: str | None = None,
    ) -> dict:
        ids = list(ids)
        if not ids:
            return self.empty_page(limit, offset)
        params: dict = {"ids": ids}
        if search is not None:
            params["search"] = search
        if order is not None:
            params["order"] = order
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


class SandboxCustomLibraryClient(SandboxClient):
    """The sandbox's custom libraries and the wheels stored under them."""

    def list(
        self,
        *,
        ids: Iterable[str],
        limit: str | None = None,
        offset: str | None = None,
    ) -> dict:
        ids = list(ids)
        if not ids:
            return self.empty_page(limit, offset)
        params: dict = {"ids": ids}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        response = self.get(url="/custom-libraries", params=params)
        return response.json()

    def retrieve(self, library_id: str) -> dict:
        response = self.get(url=f"/custom-libraries/{library_id}")
        return response.json()

    def create(self, data: dict) -> dict:
        response = self.post(url="/custom-libraries", json=data)
        return response.json()

    def update(self, library_id: str, data: dict) -> dict:
        response = self.patch(url=f"/custom-libraries/{library_id}", json=data)
        return response.json()

    def remove(self, library_id: str) -> None:
        self.delete(url=f"/custom-libraries/{library_id}")

    def list_wheels(self, library_id: str) -> list[dict]:
        response = self.get(url=f"/custom-libraries/{library_id}/wheels")
        return response.json()

    def retrieve_wheel(self, library_id: str, wheel_id: str) -> dict:
        response = self.get(url=f"/custom-libraries/{library_id}/wheels/{wheel_id}")
        return response.json()

    def upload_wheel(self, library_id: str, file: UploadedFile) -> dict:
        response = self.post(
            url=f"/custom-libraries/{library_id}/wheels",
            files={"file": (file.name, file, file.content_type)},
        )
        return response.json()

    def remove_wheel(self, library_id: str, wheel_id: str) -> None:
        self.delete(url=f"/custom-libraries/{library_id}/wheels/{wheel_id}")

    def download_wheel(self, library_id: str, wheel_id: str) -> tuple[bytes, str | None]:
        """The wheel's bytes and the `content-disposition` the sandbox named it with.

        The header is handed on as it arrived rather than taken apart and built
        again: the name the file is saved under is the sandbox's to decide.
        """
        response = self.get(url=f"/custom-libraries/{library_id}/wheels/{wheel_id}/file")
        return response.content, response.headers.get("content-disposition")
