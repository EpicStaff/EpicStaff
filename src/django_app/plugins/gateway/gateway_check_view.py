from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from plugins.gateway.gateway_service import GatewayCheckRequest, GatewayDecisionService

_decisions = GatewayDecisionService()


@require_GET
async def gateway_check(request: HttpRequest) -> HttpResponse:
    """nginx's `auth_request` for every `/api/` request on a plugin host.

    A plain asynchronous Django view without DRF authentication: nginx proves itself with
    the gateway secret and sends only the headers the check needs, never the client's
    cookies. nginx answers 404 to this path from outside, so only nginx's own subrequest
    reaches it.
    """
    decision = await _decisions.decide_async(GatewayCheckRequest.from_meta(request.META))
    response = HttpResponse(status=decision.status)
    for name, value in decision.headers.items():
        response[name] = value
    return response
