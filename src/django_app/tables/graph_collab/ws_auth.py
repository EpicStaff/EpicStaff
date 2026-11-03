from asgiref.sync import sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rbac.identity.tickets import ws_ticket_service


class TicketAuthMiddleware(BaseMiddleware):
    """
    ASGI middleware that resolves a ?ticket=<value> query param into a User
    and sets scope["user"]. Sets AnonymousUser when the ticket is missing or
    expired — the consumer decides whether to reject the connection.
    Sets scope["api_key_org_id"] to the org of the USER API key the ticket was
    issued with, or None; the consumer must refuse any other org's row.
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        ticket = self._extract_ticket(query_string)
        holder = await sync_to_async(ws_ticket_service.consume)(ticket)
        scope["user"] = holder.user if holder else AnonymousUser()
        scope["api_key_org_id"] = holder.api_key_org_id if holder else None
        await super().__call__(scope, receive, send)

    @staticmethod
    def _extract_ticket(query_string: str) -> str:
        for part in query_string.split("&"):
            if part.startswith("ticket="):
                return part[len("ticket=") :]
        return ""
