FORWARDING_HEADER_NAMES = frozenset(
    {
        b"x-forwarded-for",
        b"x-forwarded-proto",
        b"x-forwarded-host",
        b"x-forwarded-port",
        b"x-real-ip",
    }
)


class DropUnderscoreForwardingHeadersMiddleware:
    """Drop underscore spellings of the forwarding headers before the app sees them.

    Django builds META by upper-casing a header name and turning dashes into
    underscores, so `X_Forwarded_For` and `X-Forwarded-For` both land in
    `HTTP_X_FORWARDED_FOR`, joined with a comma. The proxy only overwrites the
    dash spelling; a client-sent underscore spelling then follows it, and DRF
    (`NUM_PROXIES`) reads the last entry, which lets a caller choose the address
    every throttle keys on. Dropping the underscore spellings here keeps that
    closed even if the proxy stops stripping them. Other headers, including
    other underscore headers, pass through untouched.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {
                **scope,
                "headers": [
                    (name, value)
                    for name, value in scope["headers"]
                    if not _is_underscore_forwarding_header(name)
                ],
            }
        await self.app(scope, receive, send)


def _is_underscore_forwarding_header(name: bytes) -> bool:
    return b"_" in name and name.lower().replace(b"_", b"-") in FORWARDING_HEADER_NAMES
