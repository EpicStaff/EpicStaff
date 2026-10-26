"""What a plugin page may ask of EpicStaff: the token exchange, and the authorize navigation.

Plugin hosts share a site with EpicStaff, so the browser sends EpicStaff's `SameSite=Lax`
cookie with a plugin page's requests, and Django's CSRF check does not apply to the API. Every
request whose `Origin` lies in the plugin base domain is therefore refused here, before any
view runs, except:

- the token exchange from an exact plugin frame origin: `POST`, and its CORS preflight, which
  this middleware answers itself (no credentials are ever allowed);
- `GET` authorize, a navigation that normally carries no `Origin` at all.

A page can also hide its origin: with `referrerPolicy: 'no-referrer'` (or from a sandboxed
frame) its requests carry `Origin: null`. Such a request is refused when it could write the
refresh cookie or act on it: any method but `GET`, `HEAD` and `OPTIONS` under `/api/auth/`, and
the password-change confirm. Requests elsewhere authenticate only with a header such a page
cannot send without a CORS preflight, which `null` never passes, so they are left alone.

It sits immediately before `corsheaders.middleware.CorsMiddleware`: that middleware answers
every preflight itself without calling the middleware after it, so only a middleware in front
of it sees the token endpoint's preflight. It reads `PLUGINS_ENABLED` on every request and
does nothing while the platform is off.
"""

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.cache import patch_vary_headers

from plugins.audit import log_origin_refused
from plugins.exceptions import PluginOriginRefusedError
from plugins.identity.login_protocol import AUTHORIZE_PATH, TOKEN_PATH
from plugins.origins import PluginOrigins

PREFLIGHT_MAX_AGE_SECONDS = 600
NULL_ORIGIN = "null"
# Where the refresh cookie is read or written. The password-change confirm sits outside
# /api/auth/ but sets the cookie too (`rbac.urls`, name `profile_password_change_confirm`).
REFRESH_COOKIE_PATH_PREFIX = "/api/auth/"
PASSWORD_CHANGE_CONFIRM_PATH = "/api/profile/password-change/confirm/"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOKEN_REQUEST_HEADERS = frozenset({"content-type"})
_CORS_HEADER_PREFIX = "access-control-"


class _Verdict:
    """The policy's answer for one request: a response of its own, or how to finish the view's."""

    def __init__(
        self,
        response: HttpResponse | None = None,
        cors_origin: str | None = None,
        strip_cors: bool = False,
    ):
        self.response = response
        self._cors_origin = cors_origin
        self._strip_cors = strip_cors

    def finish(self, response: HttpResponse) -> HttpResponse:
        if self._strip_cors:
            _drop_cors_headers(response)
        if self._cors_origin is not None:
            response["Access-Control-Allow-Origin"] = self._cors_origin
            patch_vary_headers(response, ("Origin",))
        return response


_UNJUDGED = _Verdict()


class PluginOriginPolicyMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self.async_mode = iscoroutinefunction(get_response)
        if self.async_mode:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self.async_mode:
            return self.__acall__(request)
        verdict = _judge(request)
        if verdict.response is not None:
            return verdict.response
        return verdict.finish(self.get_response(request))

    async def __acall__(self, request):
        verdict = _judge(request)
        if verdict.response is not None:
            return verdict.response
        return verdict.finish(await self.get_response(request))


def _judge(request) -> _Verdict:
    if not settings.PLUGINS_ENABLED:
        return _UNJUDGED
    origin = request.headers.get("Origin")
    if origin is None:
        return _UNJUDGED
    if origin.lower() == NULL_ORIGIN:
        return _refused(request, origin) if _touches_refresh_cookie(request) else _UNJUDGED
    origins = PluginOrigins()
    if not origins.is_plugin_domain_origin(origin):
        return _UNJUDGED
    path = request.path_info
    if path == TOKEN_PATH and origins.identifier_from_origin(origin) is not None:
        if request.method == "POST":
            return _Verdict(cors_origin=origin, strip_cors=True)
        if request.method == "OPTIONS" and _is_token_preflight(request):
            return _Verdict(response=_preflight_response(origin))
    if path == AUTHORIZE_PATH and request.method == "GET":
        return _Verdict(strip_cors=True)
    return _refused(request, origin)


def _touches_refresh_cookie(request) -> bool:
    path = request.path_info
    return request.method not in SAFE_METHODS and (
        path.startswith(REFRESH_COOKIE_PATH_PREFIX) or path == PASSWORD_CHANGE_CONFIRM_PATH
    )


def _refused(request, origin: str) -> _Verdict:
    log_origin_refused(origin=origin, method=request.method, path=request.path_info)
    return _Verdict(response=_refusal())


def _is_token_preflight(request) -> bool:
    if request.headers.get("Access-Control-Request-Method") != "POST":
        return False
    requested = {
        header.strip().lower()
        for header in request.headers.get("Access-Control-Request-Headers", "").split(",")
        if header.strip()
    }
    return requested <= TOKEN_REQUEST_HEADERS


def _preflight_response(origin: str) -> HttpResponse:
    response = HttpResponse(status=204)
    response["Access-Control-Allow-Origin"] = origin
    response["Access-Control-Allow-Methods"] = "POST"
    response["Access-Control-Allow-Headers"] = "content-type"
    response["Access-Control-Max-Age"] = str(PREFLIGHT_MAX_AGE_SECONDS)
    patch_vary_headers(response, ("Origin",))
    return response


def _refusal() -> JsonResponse:
    error = PluginOriginRefusedError()
    return JsonResponse(
        {
            "status_code": error.status_code,
            "code": error.default_code,
            "message": str(error.detail),
        },
        status=error.status_code,
    )


def _drop_cors_headers(response: HttpResponse) -> None:
    # Above all Access-Control-Allow-Credentials: a plugin page must never read a response
    # its request made with EpicStaff's cookies, even with a plugin host in the CORS list.
    for name in [name for name in response.headers if name.lower().startswith(_CORS_HEADER_PREFIX)]:
        del response[name]
