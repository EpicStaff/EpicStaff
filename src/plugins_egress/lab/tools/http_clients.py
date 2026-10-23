"""Lab only: httpx and requests take the proxy, credentials included, from HTTPS_PROXY by default."""

import httpx
import requests

ALLOWED = "https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1"
UNDECLARED = "https://example.com/"

for name, get in (
    ("httpx", lambda url: httpx.get(url, timeout=20)),
    ("requests", lambda url: requests.get(url, timeout=20)),
):
    print(f"{name} declared={get(ALLOWED).status_code}", end=" ")
    try:
        get(UNDECLARED)
        print("undeclared=reached")
    except (
        Exception
    ) as error:  # Each library raises its own proxy error; its class name is the result.
        print(f"undeclared={type(error).__name__}")
