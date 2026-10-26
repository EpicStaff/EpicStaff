from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from plugins.development.development_targets import DevelopmentPageDecisionService

_page_decisions = DevelopmentPageDecisionService()


@require_GET
async def development_spa_check(request: HttpRequest) -> HttpResponse:
    """nginx's sub-request before it serves a plugin page in plugin development mode.

    A plain asynchronous Django view without DRF authentication, like the gateway check:
    nginx proves itself with the gateway secret and sends only that and the plugin's
    identifier. nginx answers 404 to this path from outside, and asks it only while
    development mode is on, so a deployment without the mode never calls it for a page.
    """
    decision = await _page_decisions.decide_async(
        request.META.get("HTTP_X_PLUGIN_GATEWAY_SECRET", ""),
        request.META.get("HTTP_X_PLUGIN_IDENTIFIER", ""),
    )
    response = HttpResponse(status=decision.status)
    for name, value in decision.headers.items():
        response[name] = value
    return response
