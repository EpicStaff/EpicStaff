"""The files of a plugin's own page, served to its sandboxed iframe.

A plain Django view on purpose: no DRF, no JWT, no session. The frame carries no
credentials, so the signed token in the URL is the whole authorization, and the
response must never set a cookie or read one.
"""

from django.http import HttpRequest, HttpResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET

from plugins.services.ui_service import PluginUiService

# `sandbox` re-applies the iframe's own sandbox even if the file is opened
# directly, so the page never gets this origin. Scripts and styles may come only
# from the page's own files; it can fetch, frame, post or navigate nowhere.
CONTENT_SECURITY_POLICY = (
    "sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; "
    "object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
)

ASSET_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    # The sandboxed page has an opaque origin, and `same-origin` / `same-site` would
    # block its own <script src>, <link href> and <img> loads. The unguessable,
    # expiring token in the URL is what keeps other sites from reading these files.
    "Cross-Origin-Resource-Policy": "cross-origin",
}


@require_GET
@xframe_options_sameorigin
def plugin_ui_asset(request: HttpRequest, token: str, asset_path: str) -> HttpResponse:
    """One file of a plugin page, or an empty 404 for any failure whatsoever."""
    asset = PluginUiService().find_asset(token, asset_path)
    if asset is None:
        return HttpResponse(status=404, content_type="text/plain; charset=utf-8")
    response = HttpResponse(asset.content, content_type=asset.content_type)
    for name, value in ASSET_HEADERS.items():
        response[name] = value
    return response
