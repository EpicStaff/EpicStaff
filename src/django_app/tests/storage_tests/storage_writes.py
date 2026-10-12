"""Storage writes for tests: seed a stored object, or upload through the real endpoint."""

from urllib.parse import urlencode

import httpx
from asgiref.sync import sync_to_async
from rest_framework_simplejwt.tokens import AccessToken

from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.path_utils import storage_key
from tables.views.storage_upload_stream_view import UPLOAD_STREAM_PATH


def store_object(backend, org_id: int, path: str, data: bytes, user=None) -> None:
    """Put an object in storage and seed its row via `on_upload`, authored by `user`."""
    backend.put_bytes(storage_key(org_id, path), data)
    StorageFileSync.on_upload(org_id, path, size=len(data), user=user)


@sync_to_async
def _access_token(user) -> str:
    return str(AccessToken.for_user(user))


async def stream_upload(
    user, org, path: str, filename: str, content: bytes = b"data", *, api_key: str | None = None
):
    """Upload through the real streaming endpoint, as the browser does.

    Authenticates as `user` with a JWT, or with `api_key` when one is given.
    """
    from django_app.asgi import application

    query = urlencode({"path": path, "filename": filename})
    credentials = (
        {"X-API-Key": api_key}
        if api_key is not None
        else {"Authorization": f"Bearer {await _access_token(user)}"}
    )
    headers = {**credentials, "X-Organization-Id": str(org.id)}
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"{UPLOAD_STREAM_PATH}?{query}", content=content, headers=headers)
