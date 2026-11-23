# Remote GitHub Search Tool
import os
import tempfile
import shutil
import subprocess
from typing import List, Optional
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


# Copied verbatim from web_fetch_tool/main.py, like `_ssrf_guard` above.
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


def _pin_host_to_vetted_address(url: str):
    """Resolve the host once and return (curl resolve entry or None, error or None).

    git would otherwise resolve the host a second time, after `_ssrf_guard`
    has already checked it, so a host answering public-then-internal could
    reach an internal address. The returned entry makes git connect to the
    address vetted here.
    """
    import ipaddress
    import socket

    import httpx

    parsed = httpx.URL(url)
    host = parsed.host
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        ipaddress.ip_address(host)
        # An IP literal involves no DNS lookup, so there is nothing to pin.
        return None, None
    except ValueError:
        pass

    # curl converts a non-ASCII host to punycode before its lookup but matches
    # resolve entries as written, so the pin would not apply and curl would
    # resolve the host itself.
    if not host.isascii():
        return None, f"Error: '{host}' is not an ASCII host name."

    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return None, f"Error: could not resolve host '{host}': {e}"

    for info in addr_infos:
        raw_ip = info[4][0]
        if _is_internal_address(raw_ip):
            return (
                None,
                f"Error: refusing to fetch {url} — host '{host}' resolves to a "
                f"private/internal address ({raw_ip}). Blocked to prevent SSRF.",
            )

    if not addr_infos:
        return None, f"Error: could not resolve host '{host}'."

    vetted_ip = addr_infos[0][4][0]
    if ":" in vetted_ip:
        # curl's CURLOPT_RESOLVE wants IPv6 addresses inside brackets.
        vetted_ip = f"[{vetted_ip}]"
    return f"{host}:{port}:{vetted_ip}", None


def main(
    search_query: str,
    repo_path_or_url: str,
    file_types: Optional[List[str]] = None
) -> str:
    """
    Search a public Git repo, given by its http(s) URL, for a query.

    Args:
        search_query (str): Query string to search.
        repo_path_or_url (str): http(s) URL of the repo, e.g. a GitHub URL.
        file_types (List[str], optional): List of file extensions to include.

    Returns:
        str: Matching file paths and snippet lines.
    """
    url = urlparse(repo_path_or_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        return f"Error: '{repo_path_or_url}' is not an http(s) URL"

    ok, err = _ssrf_guard(repo_path_or_url)
    if not ok:
        return err

    resolve_entry, err = _pin_host_to_vetted_address(repo_path_or_url)
    if err:
        return err
    pin_options = ["-c", f"http.curloptResolve={resolve_entry}"] if resolve_entry else []

    temp_dir = tempfile.mkdtemp()
    try:
        print(f"Cloning remote repo {repo_path_or_url} into {temp_dir} ...")
        try:
            # Redirects are off so git cannot be sent past `_ssrf_guard`, and
            # `http.curloptResolve` pins git to the address vetted by
            # `_pin_host_to_vetted_address`, which closes DNS rebinding between
            # the guard's lookup and git's own. The sandbox egress firewall
            # remains the backstop for dumb-HTTP alternates that name another
            # host and for a URL that git parses to a different host than
            # `_ssrf_guard` does.
            subprocess.run(
                [
                    "git",
                    "-c",
                    "http.followRedirects=false",
                    *pin_options,
                    "clone",
                    "--depth",
                    "1",
                    repo_path_or_url,
                    temp_dir,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            return f"Error cloning repo: {e.stderr.decode()}"
        except OSError as e:
            return f"Error cloning repo: could not run git ({e})"

        matches = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file_types and not any(file.endswith(ft) for ft in file_types):
                    continue
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f, 1):
                            if search_query.lower() in line.lower():
                                matches.append(f"{file_path} (line {i}): {line.strip()}")
                except Exception as e:
                    matches.append(f"{file_path}: Error reading file ({e})")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if not matches:
        return "No matches found."
    return "\n".join(matches)