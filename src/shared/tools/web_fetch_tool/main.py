# Web Fetch Tool
#
# Note: no in-memory cache is used here (unlike the original tool-service
# implementation) because each sandbox execution runs in a fresh process —
# an in-process cache would never be reused across calls anyway.

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
DOWNLOAD_CAP_BYTES = 5 * 1024 * 1024

_HTML_CONTENT_TYPES = ("", "text/html", "application/xhtml+xml")
_PASSTHROUGH_PREFIXES = ("text/",)
_PASSTHROUGH_CONTENT_TYPES = ("application/json", "application/xml")


def _ssrf_guard(url: str):
    import ipaddress
    import socket

    import httpx

    try:
        parsed = httpx.URL(url)
    except Exception as e:
        return False, f"Error: invalid URL '{url}': {e}"

    if parsed.scheme not in ("http", "https"):
        return (
            False,
            f"Error: unsupported URL scheme '{parsed.scheme}' — only http and "
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
                f"Error: refusing to fetch {url} — host '{host}' resolves to a "
                f"private/internal address ({raw_ip}). Blocked to prevent SSRF.",
            )

    return True, None


def _convert_body(body: bytes, content_type: str, truncated: bool, url: str):
    content_type_main = content_type.split(";")[0].strip().lower()

    note = ""
    if truncated:
        cap_mb = DOWNLOAD_CAP_BYTES // (1024 * 1024)
        note = f"\n\n(download truncated at the {cap_mb} MB cap)"

    if content_type_main in _HTML_CONTENT_TYPES:
        text = body.decode("utf-8", errors="replace")

        markdown = None
        try:
            import trafilatura

            markdown = trafilatura.extract(
                text,
                output_format="markdown",
                include_links=True,
                include_tables=True,
                url=url,
            )
        except Exception:
            markdown = None

        if not markdown:
            try:
                from markdownify import markdownify as md

                markdown = md(text)
            except Exception as e:
                return (
                    None,
                    f"Error: could not convert HTML from {url} to markdown: {e}",
                )

        return markdown + note, None

    if content_type_main.startswith(_PASSTHROUGH_PREFIXES) or (
        content_type_main in _PASSTHROUGH_CONTENT_TYPES
    ):
        text = body.decode("utf-8", errors="replace")
        return text + note, None

    return (
        None,
        f"Error: cannot convert binary content of type '{content_type_main}' "
        f"from {url} to text.",
    )


def _fetch_and_convert(url: str):
    import httpx

    current_url = url
    original_host = httpx.URL(url).host

    with httpx.Client(
        timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            ok, err = _ssrf_guard(current_url)
            if not ok:
                return None, err

            try:
                with client.stream("GET", current_url) as response:
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location:
                            return (
                                None,
                                f"Error: redirect response from {current_url} "
                                "had no Location header.",
                            )
                        next_url = str(httpx.URL(current_url).join(location))
                        next_host = httpx.URL(next_url).host
                        if next_host != original_host:
                            return (
                                None,
                                f"Redirects to {next_url} — call again with that URL",
                            )
                        current_url = next_url
                        continue

                    if response.status_code >= 400:
                        return (
                            None,
                            f"Error: fetching {current_url} failed with status "
                            f"{response.status_code}.",
                        )

                    content_type = response.headers.get("content-type", "")
                    body = bytearray()
                    truncated = False
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > DOWNLOAD_CAP_BYTES:
                            truncated = True
                            break

                    return _convert_body(
                        bytes(body), content_type, truncated, current_url
                    )
            except httpx.HTTPError as e:
                return None, f"Error: network failure while fetching {current_url}: {e}"

        return (
            None,
            f"Error: exceeded max redirects ({MAX_REDIRECTS}) while fetching {url}.",
        )


def main(url: str) -> str:
    """
    Fetch a URL and convert it to markdown (or pass through plain text/JSON).
    Refuses private/loopback/link-local addresses (SSRF guard) and does not
    follow cross-host redirects. Never raises: all failures are returned as
    readable error strings.
    """
    try:
        import httpx

        if not url:
            return "Error: url argument is mandatory and was not given to the tool."

        try:
            parsed = httpx.URL(url)
        except Exception as e:
            return f"Error: invalid URL '{url}': {e}"

        if parsed.scheme not in ("http", "https"):
            return (
                f"Error: unsupported URL scheme '{parsed.scheme}'. Only http and "
                "https URLs are supported."
            )

        normalized_url = url
        if parsed.scheme == "http":
            normalized_url = "https://" + url.split("://", 1)[1]

        markdown, error = _fetch_and_convert(normalized_url)
        if error:
            return error

        return markdown
    except Exception as e:
        return f"Error: failed to fetch URL. Unexpected exception: {e}"
