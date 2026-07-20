from asgiref.sync import sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser

from tables.services.rbac.ticket_service import ws_ticket_service


class TicketAuthMiddleware(BaseMiddleware):
    """
    ASGI middleware that resolves a ?ticket=<value> query param into a User
    and sets scope["user"]. Sets AnonymousUser when the ticket is missing or
    expired — the consumer decides whether to reject the connection.
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        ticket = self._extract_ticket(query_string)
        scope["user"] = (
            await sync_to_async(ws_ticket_service.consume)(ticket) or AnonymousUser()
        )
        await super().__call__(scope, receive, send)

    @staticmethod
    def _extract_ticket(query_string: str) -> str:
        for part in query_string.split("&"):
            if part.startswith("ticket="):
                return part[len("ticket=") :]
        return ""
