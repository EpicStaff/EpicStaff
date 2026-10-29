"""The two EpicStaff steps of a plugin login: authorize (browser navigation) and token exchange.

A plugin page logs a person in as an OAuth public client with PKCE: it sends the browser to
`plugin-authorize`, which reads EpicStaff's session from the refresh cookie and redirects back
to the plugin's callback page with a one-time code; the page then exchanges the code for a
plugin login token at `plugin-token`. See docs/plugins/reference/token-exchange.md.
"""

from django.http import HttpResponseRedirect
from epicstaff_plugin.problems import Problem
from rbac.identity.refresh_cookie import get_refresh_from_cookie
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.access.plugin_access import loginable_plugin
from plugins.exceptions import InvalidTokenRequestError
from plugins.identity.plugin_authorization import PluginAuthorizationService
from plugins.identity.refresh_session import user_for_refresh_token
from plugins.identity.token_exchange import PluginTokenExchangeService
from plugins.serializers.login import (
    TOKEN_BODY_LOC,
    PluginTokenResponseSerializer,
    parse_authorize_query,
    parse_token_request,
)
from plugins.throttles import PluginTokenIpThrottle

JSON_MEDIA_TYPE = "application/json"


class _NoStoreView(APIView):
    """Every answer, errors included, is personal and single-use: no cache may keep it."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class PluginAuthorizeView(_NoStoreView):
    """`GET /api/auth/plugin-authorize/`: EpicStaff's half of a plugin login, as a redirect.

    The only GET in EpicStaff that reads the refresh cookie. It only reads it: it never
    rotates or blacklists the token and never sets a cookie. A malformed request or a plugin
    one cannot log in to is answered with JSON, never a redirect.
    """

    _service = PluginAuthorizationService()

    def get(self, request):
        query = parse_authorize_query(request.query_params)
        plugin = loginable_plugin(query.plugin)
        user = user_for_refresh_token(get_refresh_from_cookie(request))
        return HttpResponseRedirect(self._service.redirect_target(query, plugin, user))


class PluginTokenView(_NoStoreView):
    """`POST /api/auth/plugin-token/`: a code and its PKCE verifier for a plugin login token.

    Cookie-blind: it never reads a cookie and never sets one, so a browser's ambient session
    cannot be used here; the code alone names the person. Only `application/json` is taken,
    which a cross-origin page cannot send without a preflight; the Origin policy answers the
    preflight for plugin origins only.
    """

    throttle_classes = [PluginTokenIpThrottle]
    parser_classes = [JSONParser]

    _service = PluginTokenExchangeService()

    def post(self, request):
        # Before the body is read: DRF skips the parser, and so its 415, for an empty body.
        if _media_type(request.content_type) != JSON_MEDIA_TYPE:
            raise UnsupportedMediaType(request.content_type)
        try:
            body = request.data
        except ParseError:
            raise InvalidTokenRequestError([Problem(TOKEN_BODY_LOC, "is not valid JSON")]) from None
        code, code_verifier = parse_token_request(body)
        login = self._service.exchange(
            code=code, code_verifier=code_verifier, origin=request.headers.get("Origin")
        )
        return Response(PluginTokenResponseSerializer(login).data)


def _media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()
