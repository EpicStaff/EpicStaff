"""The files of a plugin's own page, served to its sandboxed iframe.

A plain Django view on purpose: no DRF, no JWT, no session. The frame carries no
credentials, so the signed token in the URL is the whole authorization, and the
response must never set a cookie or read one.
"""

import posixpath

from django.http import HttpRequest, HttpResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET

from plugins.manifest import UI_CONTENT_TYPES
from plugins.services.ui_service import PluginUiService

# `sandbox` re-applies the iframe's own sandbox even if the file is opened
# directly, so the page never gets this origin. Scripts may come only from the
# page's own files (no inline script, no eval); it can fetch, frame, post or
# navigate nowhere. Inline styles are allowed because frameworks inject them at
# run time; `data:`/`blob:` images and `data:` fonts never leave the page.
CONTENT_SECURITY_POLICY = (
    "sandbox allow-scripts; default-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
    "connect-src 'none'; media-src 'none'; frame-src 'none'; worker-src 'none'; "
    "manifest-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'self'"
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
    # The page's origin is opaque (`null`), and module scripts, module chunks and web
    # fonts are fetched in CORS mode, so without this none of them would load. Safe
    # for the same reason as above: nothing here is credentialed; the token is all.
    "Access-Control-Allow-Origin": "*",
}


# Plugin documents are only ever rendered inside the host page's sandboxed frame. A
# page can read its own URL and navigate away with it, so a leaked link must not open
# as a top-level page: it would act as a page on EpicStaff's own domain (a fake
# sign-in, say) for as long as its token lives. Fetch Metadata tells the two apart:
# a navigation must target an iframe, and a document request without Fetch Metadata
# (every current browser sends it) is refused. Scripts, styles, fonts and images load
# as subresources and are unaffected, also without the headers, so a static file can
# still be fetched by hand for debugging. Sec-Fetch-Site cannot help: the sandboxed
# frame's origin is opaque, so even its own requests are `cross-site`.
NAVIGATION_MODES = frozenset({"navigate", "nested-navigate"})
DOCUMENT_TYPES = frozenset({UI_CONTENT_TYPES[".html"], UI_CONTENT_TYPES[".svg"]})


@require_GET
@xframe_options_sameorigin
def plugin_ui_asset(request: HttpRequest, token: str, asset_path: str) -> HttpResponse:
    """One file of a plugin page, or an empty 404 for any failure whatsoever."""
    if not _loaded_by_the_frame(request, asset_path):
        return _not_found()
    asset = PluginUiService().find_asset(token, asset_path)
    if asset is None:
        return _not_found()
    response = HttpResponse(asset.content, content_type=asset.content_type)
    for name, value in ASSET_HEADERS.items():
        response[name] = value
    return response


def _loaded_by_the_frame(request: HttpRequest, asset_path: str) -> bool:
    """False for a top-level navigation, and for a document requested without Fetch Metadata."""
    destination = request.headers.get("Sec-Fetch-Dest")
    if request.headers.get("Sec-Fetch-Mode") in NAVIGATION_MODES and destination != "iframe":
        return False
    served_type = UI_CONTENT_TYPES.get(posixpath.splitext(asset_path)[1].lower())
    return destination is not None or served_type not in DOCUMENT_TYPES


def _not_found() -> HttpResponse:
    return HttpResponse(status=404, content_type="text/plain; charset=utf-8")
