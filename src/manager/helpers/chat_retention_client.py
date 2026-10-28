from datetime import UTC, datetime

import httpx

PURGE_PATH = "/chat/internal/v1/retention/purge"
INTERNAL_API_KEY_HEADER = "X-Internal-Api-Key"
# The chat deletes in committed batches before it answers, so a large backlog takes a while.
DEFAULT_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class ChatRetentionError(Exception):
    """The chat service did not confirm a purge: unreachable, rejected it, or answered nonsense."""


class ChatRetentionClient:
    """Asks the chat service to delete an organization's expired conversations.

    Calls the chat directly (``CHAT_UPSTREAM_URL``), not through nginx, which hides
    ``/chat/internal/`` from the outside.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    async def purge(self, org_id: int, older_than: datetime) -> int:
        """Delete the organization's closed conversations with no activity since ``older_than``.

        Args:
            older_than: Aware datetime, not in the future; sent in UTC.

        Returns:
            Conversations the chat deleted.

        Raises:
            ChatRetentionError: The request failed or the response was not ``{"deleted": int}``.
                The chat may have deleted some conversations before failing; it logs them.
        """
        body = {"org_id": org_id, "older_than": older_than.astimezone(UTC).isoformat()}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(
                    f"{self.base_url}{PURGE_PATH}",
                    json=body,
                    headers={INTERNAL_API_KEY_HEADER: self.api_key},
                )
        except httpx.HTTPError as error:
            raise ChatRetentionError(f"chat purge request failed: {error}") from error

        if response.status_code != httpx.codes.OK:
            raise ChatRetentionError(
                f"chat purge answered {response.status_code}: {response.text[:500]}"
            )
        try:
            deleted = response.json()["deleted"]
        except (ValueError, KeyError, TypeError) as error:
            raise ChatRetentionError(
                f"chat purge answered without a deleted count: {response.text[:500]}"
            ) from error
        if isinstance(deleted, bool) or not isinstance(deleted, int):
            raise ChatRetentionError(
                f"chat purge answered a non-integer deleted count: {deleted!r}"
            )
        return deleted
