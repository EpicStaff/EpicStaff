import contextlib
from typing import Optional
import requests
from urllib.parse import urlparse


# Copied verbatim from web_fetch_tool/main.py's `_ssrf_guard` (kept in sync
# manually -- sandbox tools have no imports from the rest of the codebase /
# other tools, only main.py's source text is uploaded and executed).
def _ssrf_guard(url: str):
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
        if _is_internal_address(raw_ip):
            return (
                False,
                f"Error: refusing to fetch {url} — host '{host}' resolves to a "
                f"private/internal address ({raw_ip}). Blocked to prevent SSRF.",
            )

    return True, None


# Copied verbatim from web_fetch_tool/main.py together with
# `_public_only_resolution` below, like `_ssrf_guard` above.
def _is_internal_address(raw_ip: str) -> bool:
    import ipaddress

    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


# Rechecks every address an HTTP client is about to connect to. `_ssrf_guard`
# resolves the host once and the client resolves it again to connect, so a DNS
# name answering public first and internal second (rebinding) would pass the
# guard alone. httpx and requests both resolve through socket.getaddrinfo, so
# the addresses checked here are exactly the ones connected to.
# shortcut: swaps socket.getaddrinfo for the whole process while active; safe
# because each sandbox execution is its own single-threaded subprocess. Pin the
# connection to the checked address instead if tools ever share a process.
@contextlib.contextmanager
def _public_only_resolution():
    import socket

    resolve = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        address_infos = resolve(host, *args, **kwargs)
        for info in address_infos:
            raw_ip = info[4][0]
            if _is_internal_address(raw_ip):
                raise socket.gaierror(
                    f"refusing to connect to '{host}': it resolves to a "
                    f"private/internal address ({raw_ip}). Blocked to prevent SSRF."
                )
        return address_infos

    socket.getaddrinfo = getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = resolve


MAX_REDIRECTS = 3


# Copied verbatim from crewai_scrape_website_tool/main.py, like every tool
# that guards requests.get (see `_ssrf_guard` above for why this can't live
# in a shared module either).
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

        with _public_only_resolution():
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


class _FetchRefused(Exception):
    pass


def read_txt_file(txt: str) -> str:
    """Load text from an http(s) URL."""
    url = urlparse(txt)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError(f"'{txt}' is not an http(s) URL")
    response, error = _guarded_get(txt)
    if error:
        raise _FetchRefused(error)
    response.raise_for_status()
    return response.content.decode("utf-8")


def search_in_text(
    text: str, search_query: str, similarity_threshold: float = 0.7, limit: int = 5
) -> str:
    """Very simple search: returns lines containing the query. For real semantic search, replace with embedding-based search."""
    results = []
    for line in text.splitlines():
        if search_query.lower() in line.lower():
            results.append(line.strip())
        if len(results) >= limit:
            break
    return "\n".join(results)


def main(
    txt: str,
    search_query: str,
    similarity_threshold: Optional[float] = 0.7,
    limit: Optional[int] = 5,
) -> str:
    """
    Entry point for TXTSearchTool.

    Args:
        txt (str): http(s) URL of a TXT file.
        search_query (str): Search query.
        similarity_threshold (float, optional): Currently unused.
        limit (int, optional): Max number of results.

    Returns:
        str: Search results.
    """
    try:
        content = read_txt_file(txt)
        results = search_in_text(
            content, search_query, similarity_threshold=similarity_threshold, limit=limit
        )
        return results if results else "No results found."
    except _FetchRefused as refusal:
        return str(refusal)
    except Exception as e:
        return f"Error: {e}"