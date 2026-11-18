import httpx
from loguru import logger


class AgentChatEndClient:
    """Reports the end of a realtime agent chat to Django.

    Django stamps the chat as ended and revokes its temporary storage account, which
    also syncs the files the session wrote into the org's file index (and so its quota).
    The call is best-effort: a failure is logged and never raised, because the account's
    TTL is the backstop and callers run it on a teardown path.
    """

    def __init__(self, django_api_base_url: str, django_api_key: str = ""):
        self.django_api_base_url = django_api_base_url
        self.django_api_key = django_api_key

    async def end_chat(self, connection_key: str, duration: float, end_reason: str) -> None:
        url = f"{self.django_api_base_url}/realtime-agent-chats/end/"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"Host": "localhost", "X-API-Key": self.django_api_key},
                    json={
                        "connection_key": connection_key,
                        "duration_seconds": round(duration, 2),
                        "end_reason": end_reason,
                    },
                    timeout=10.0,
                )
                if not resp.is_success:
                    logger.warning(
                        f"Failed to update agent chat metadata: {resp.status_code} {resp.text}"
                    )
        except Exception as e:
            logger.error(f"Error updating agent chat metadata: {e}")
