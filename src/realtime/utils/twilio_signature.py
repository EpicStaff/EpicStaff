"""Stdlib reimplementation of Twilio's webhook signature validation.

Replaces ``twilio.request_validator.RequestValidator`` (the only usage of the
``twilio`` package in this service) so the dependency can be dropped.

Mirrors ``twilio.request_validator.RequestValidator.validate()`` byte-for-byte
for the case this service actually exercises: POST form params passed as a
plain ``dict[str, str]`` (from ``dict(await request.form())`` in
``api/main.py``). In that case Twilio's own ``get_values`` helper falls back to
a single-value dict lookup (no multi-value/QueryDict/MultiDict branches), so
each param contributes exactly one ``key + value`` pair to the signed string.

Twilio's validator also guards against upstream proxies being inconsistent
about reporting the default port in the ``Host`` header: it computes the
signature twice -- once for the URL as given, once with the scheme's default
port (443 for https, 80 for http) forced onto the netloc -- and accepts either
match. That dual check is reproduced here via ``_add_port``/``_remove_port``.

The upstream validator also has a ``bodySHA256`` query-param branch used only
when ``params`` is a raw JSON string (not a dict) -- unreachable from this
service's ``/voice`` webhook, which always passes a dict, so it is not
reproduced here.
"""

import base64
import hashlib
import hmac
from urllib.parse import ParseResult, urlparse


def _remove_port(parsed: ParseResult) -> str:
    """Return the URL with any explicit port stripped from the netloc."""
    if not parsed.port:
        return parsed.geturl()
    new_netloc = parsed.netloc.split(":")[0]
    return parsed._replace(netloc=new_netloc).geturl()


def _add_port(parsed: ParseResult) -> str:
    """Return the URL with the scheme's default port forced onto the netloc."""
    if parsed.port:
        return parsed.geturl()
    port = 443 if parsed.scheme == "https" else 80
    new_netloc = f"{parsed.netloc}:{port}"
    return parsed._replace(netloc=new_netloc).geturl()


def _compute_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """Reproduce ``RequestValidator.compute_signature`` for a dict of params."""
    payload = url
    if params:
        for key in sorted(set(params)):
            payload += key + params[key]

    mac = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("utf-8").strip()


def validate_twilio_signature(
    url: str, params: dict[str, str], signature: str, auth_token: str
) -> bool:
    """Validate a Twilio webhook request's ``X-Twilio-Signature`` header.

    :param url: Full URL Twilio requested (scheme + host + path + query).
    :param params: POST form params as a plain single-valued dict.
    :param signature: Value of the ``X-Twilio-Signature`` request header.
    :param auth_token: Twilio auth token used to sign the request.
    :returns: True if the signature matches, False otherwise.
    """
    parsed = urlparse(url)
    uri_with_port = _add_port(parsed)
    uri_without_port = _remove_port(parsed)

    expected_without_port = _compute_signature(uri_without_port, params, auth_token)
    expected_with_port = _compute_signature(uri_with_port, params, auth_token)

    valid_without_port = hmac.compare_digest(expected_without_port, signature)
    valid_with_port = hmac.compare_digest(expected_with_port, signature)

    return valid_without_port or valid_with_port
