# Notification Tool
#
# EST-3285 4.8 human-in-the-loop, part (b): lets an agent push a short
# out-of-band notification without pausing the flow (unlike
# wait_for_decision_tool, this tool does not block/poll -- it fires and
# returns).
#
# channel='email': posts to the existing-infra-backed `/notify/email/`
# Django endpoint, which reuses NotificationEmailSender (Django's
# `send_mail` / `EMAIL_BACKEND` -- the SAME transport
# PasswordResetEmailSender already uses) rather than a parallel SMTP client.
# This tool itself never talks SMTP directly, exactly like subflow_tool
# never talks to the crew engine directly -- everything goes through
# django_app's REST surface.
#
# channel='webhook': a direct httpx POST to an arbitrary caller-supplied URL
# with the message as JSON. This does NOT go through django_app (there is no
# stored credential to protect), but DOES need its own SSRF guard since the
# URL is fully attacker/agent-controlled -- copied from web_fetch_tool's
# `_ssrf_guard` (duplicated here per the sandbox tool convention: each
# main.py has no imports from the rest of the codebase / other tools, only
# main.py's source text is uploaded and executed).

MAX_MESSAGE_LEN = 200
HTTP_TIMEOUT_S = 15.0
VALID_CHANNELS = {"email", "webhook"}
DEFAULT_API_BASE_URL = "http://django_app:8000/api"


def _api_base_url() -> str:
    import os

    configured = globals().get("api_base_url")
    if configured:
        return str(configured).rstrip("/")

    env_url = os.environ.get("DJANGO_API_URL")
    if env_url:
        return env_url.rstrip("/")

    return DEFAULT_API_BASE_URL


def _ssrf_guard(url: str):
    """Refuse private/loopback/link-local/reserved/multicast targets.
    Copied from web_fetch_tool/main.py's `_ssrf_guard` (kept in sync
    manually -- see module docstring for why this can't be a shared import)."""
    import ipaddress
    import socket

    import httpx

    try:
        parsed = httpx.URL(url)
    except Exception as e:
        return False, f"Error: invalid webhook URL '{url}': {e}"

    if parsed.scheme not in ("http", "https"):
        return (
            False,
            f"Error: unsupported URL scheme '{parsed.scheme}' -- only http and "
            "https are allowed.",
        )

    host = parsed.host
    if not host:
        return False, f"Error: could not determine host from URL {url}."

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return False, f"Error: could not resolve host '{host}': {e}"

    for info in addr_infos:
        raw_ip = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return (
                False,
                f"Error: refusing to notify {url} -- host '{host}' resolves to "
                f"a private/internal address ({raw_ip}). Blocked to prevent "
                "SSRF.",
            )

    return True, None


def _send_email(message: str, target: str, note: str) -> str:
    import httpx

    api_key = globals().get("api_key")
    if not api_key:
        return (
            "Error: 'api_key' is missing. Configure an EpicStaff API key for "
            "this tool before sending email notifications."
        )

    base_url = _api_base_url()
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    payload = {"to": target, "subject": "EpicStaff notification", "message": message}

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
            response = client.post(
                f"{base_url}/notify/email/", json=payload, headers=headers
            )
    except httpx.HTTPError as e:
        return (
            "Error: could not reach the EpicStaff API to send the email "
            f"notification: {str(e)[:300]}"
        )

    if response.status_code not in (200, 201):
        return (
            f"Error: failed to send email notification to {target}, status "
            f"{response.status_code}: {response.text[:300]}"
        )

    return f"Notification email sent to {target}.{note}"


def _send_webhook(message: str, target: str, note: str) -> str:
    import httpx

    ok, err = _ssrf_guard(target)
    if not ok:
        return err

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=False) as client:
            response = client.post(target, json={"message": message})
    except httpx.HTTPError as e:
        return f"Error: could not reach webhook URL {target}: {str(e)[:300]}"

    if 300 <= response.status_code < 400:
        # Refuse to follow webhook redirects: a public URL that 302s to a
        # private/loopback/link-local address would bypass the pre-request
        # _ssrf_guard (TOCTOU SSRF). Do not log message/target beyond what's
        # already in the returned string.
        location = response.headers.get("location", "<no Location header>")
        return (
            f"Error: webhook URL returned a redirect (status "
            f"{response.status_code}) to {location}; refusing to follow for "
            "security. Provide a direct non-redirecting webhook URL."
        )

    if response.status_code >= 400:
        return (
            f"Error: webhook POST to {target} failed with status "
            f"{response.status_code}: {response.text[:300]}"
        )

    return f"Notification sent to webhook {target}.{note}"


def main(
    message: str | None = None,
    channel: str | None = None,
    target: str | None = None,
) -> str:
    """
    Send a short (<=200 char) notification via email or webhook. Never
    raises: all failures are returned as readable error strings.
    """
    try:
        if not message or not isinstance(message, str):
            return "Error: 'message' is required and must be a non-empty string."

        note = ""
        if len(message) > MAX_MESSAGE_LEN:
            message = message[:MAX_MESSAGE_LEN]
            note = f" (message truncated to {MAX_MESSAGE_LEN} characters)"

        if channel not in VALID_CHANNELS:
            return (
                f"Error: 'channel' must be one of {sorted(VALID_CHANNELS)} "
                f"(got {channel!r})."
            )
        if not target or not isinstance(target, str):
            return (
                "Error: 'target' is required (an email address for "
                "channel='email', or a URL for channel='webhook')."
            )

        if channel == "email":
            return _send_email(message, target, note)
        return _send_webhook(message, target, note)
    except Exception as e:
        return f"Error: notification tool failed. Unexpected exception: {e}"
