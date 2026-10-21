"""Which request paths the gateway lets through, decided on the canonical path only.

nginx picks its location by the normalised path (`$uri`: decoded, dot segments resolved,
slashes merged) but forwards the raw request URI to the plugin. A request whose raw path is
not already canonical could therefore pass the gateway as one path and reach the plugin as
another, so it is refused before any other rule.
"""

import unicodedata
from urllib.parse import unquote, unquote_to_bytes

from epicstaff_plugin.contracts.manifest import PublicPath

PLATFORM_PATH_MARKER = "/_epicstaff"


def canonical_path(raw_uri: str, normalized_path: str) -> str | None:
    """Return the request's canonical path, or None when the raw path is not canonical.

    `raw_uri` is nginx's `$request_uri` (path and query, as the client sent them) and
    `normalized_path` its `$uri`. The path is canonical when decoding the raw path once
    gives exactly the normalised one, it is UTF-8 without control characters, and neither it
    nor a second decoding holds a `.` or `..` segment or reaches the platform's
    `/_epicstaff` paths. Both header values arrive as Latin-1 text, so they are compared as
    bytes.
    """
    raw_path = raw_uri.partition("?")[0]
    if not raw_path.startswith("/"):
        return None
    try:
        decoded = unquote_to_bytes(raw_path)
        normalized = normalized_path.encode("latin-1")
        path = decoded.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if decoded != normalized:
        return None
    if any(unicodedata.category(character) == "Cc" for character in path):
        return None
    twice_decoded = unquote(path)
    for candidate in (path, twice_decoded):
        if _has_dot_segment(candidate) or PLATFORM_PATH_MARKER in candidate.lower():
            return None
    return path


def _has_dot_segment(path: str) -> bool:
    return any(segment in (".", "..") for segment in path.split("/"))


def match_public_path(
    public_paths: list[PublicPath], method: str, path: str
) -> tuple[int, PublicPath] | None:
    """Return the first public path rule (with its index) for this method and canonical path.

    `exact` matches the path itself. `prefix` matches the path and everything below it,
    segment by segment: `/api/public` covers `/api/public/x` but not `/api/publicity`.
    """
    for index, rule in enumerate(public_paths):
        if method not in rule.methods:
            continue
        if rule.match == "exact" and path == rule.path:
            return index, rule
        if rule.match == "prefix" and _is_under(path, rule.path):
            return index, rule
    return None


def _is_under(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(f"{prefix}/")
