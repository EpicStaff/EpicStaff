import re

from django.http import HttpResponse, JsonResponse
from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from plugins.gateway.host_proof import CHALLENGE_PATTERN, host_proof
from plugins.identity.internal_listener import holds_gateway_secret
from plugins.origins import PluginOrigins

GATEWAY_SECRET_META_KEY = "HTTP_X_PLUGIN_GATEWAY_SECRET"
IDENTIFIER_META_KEY = "HTTP_X_PLUGIN_IDENTIFIER"
CHALLENGE_META_KEY = "HTTP_X_PLUGIN_HOST_CHALLENGE"


class PluginHostProofView(APIView):
    """`GET /api/plugin-gateway/instance/`: the proof a plugin host gives that it is served here.

    nginx's `/.well-known/epicstaff/instance` location on a plugin host calls it with the
    gateway secret, the identifier its server name matched and the request's `challenge`; it
    sends none of the client's headers. nginx answers 404 to this path from outside, and
    without the gateway secret so does this view, so the proof is only ever had through a
    plugin host of this deployment. The host the proof names is the template's host for that
    identifier: the name nginx was asked for.

    Not throttled: an answer is one HMAC and touches no database, and EpicStaff's own probes
    come from django_app's address, which with hairpin NAT is the address of every client on
    the same network, so a per-address limit would let any of them make the plugins
    unavailable.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        identifier = request.META.get(IDENTIFIER_META_KEY, "")
        if not holds_gateway_secret(request.META.get(GATEWAY_SECRET_META_KEY, "")) or (
            re.fullmatch(IDENTIFIER_PATTERN, identifier) is None
        ):
            return HttpResponse(status=404)
        challenge = request.META.get(CHALLENGE_META_KEY, "")
        if re.fullmatch(CHALLENGE_PATTERN, challenge) is None:
            return JsonResponse(
                {
                    "code": "invalid_challenge",
                    "message": "challenge must be 43 base64url characters.",
                },
                status=400,
            )
        response = JsonResponse(
            {"proof": host_proof(PluginOrigins().plugin_host(identifier), challenge)}
        )
        response["Cache-Control"] = "no-store"
        return response
