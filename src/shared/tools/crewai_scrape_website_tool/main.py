import re
import requests
from typing import Optional

try:
    from bs4 import BeautifulSoup
except ImportError as e:
    raise ImportError(
        "beautifulsoup4 is required. Install with: pip install beautifulsoup4"
    ) from e


# Copied verbatim from web_fetch_tool/main.py's `_ssrf_guard` (kept in sync
# manually -- sandbox tools have no imports from the rest of the codebase /
# other tools, only main.py's source text is uploaded and executed).
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


MAX_REDIRECTS = 3


# Copied verbatim across the 4 scraping tools that guard requests.get (see
# `_ssrf_guard` above for why this can't live in a shared module either).
# `requests.get` follows redirects BY DEFAULT, which would bypass
# `_ssrf_guard` entirely (the guard checks the URL given to it, not
# wherever a 3xx response actually sends the request) -- so this walks
# redirects itself with `allow_redirects=False`, re-running `_ssrf_guard` on
# every hop, and refuses to follow any redirect that changes host (the
# caller must re-invoke the tool with that URL to get it freshly guarded).
def _guarded_get(url, headers=None, timeout=15):
    import httpx

    current_url = url
    original_host = httpx.URL(url).host

    for _hop in range(MAX_REDIRECTS + 1):
        ok, err = _ssrf_guard(current_url)
        if not ok:
            return None, err

        response = requests.get(
            current_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )

        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            if not location:
                return (
                    None,
                    f"Error: redirect response from {current_url} had no "
                    "Location header.",
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

        return response, None

    return (
        None,
        f"Error: exceeded max redirects ({MAX_REDIRECTS}) while fetching {url}.",
    )


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/96.0.4664.110 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def main(website_url: str) -> str:
    """
    Fetch and scrape text content from a website.

    Args:
        website_url (str): Website URL to scrape.

    Returns:
        str: Scraped plain text content.
    """
    ok, err = _ssrf_guard(website_url)
    if not ok:
        return err

    response, err = _guarded_get(website_url, headers=DEFAULT_HEADERS, timeout=15)
    if err:
        return err

    response.raise_for_status()
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(response.text, "html.parser")

    text = "The following text is scraped website content:\n\n"
    text += soup.get_text(" ")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+\n\s+", "\n", text)

    return text