"""Outbound HTTPS from a plugin backend, through the egress proxy.

The node gives every backend the egress proxy's URL, with the plugin's own credentials, in
`HTTPS_PROXY`, `https_proxy`, `HTTP_PROXY` and `http_proxy`, and keeps EpicStaff's internal API
and loopback direct in `NO_PROXY` and `no_proxy`. Clients that read the environment need no
code: httpx (`trust_env=True`, its default) and requests do, aiohttp does with
`trust_env=True`. The proxy lets through HTTPS on port 443 to the hosts the manifest's
`outbound_hosts` lists, and nothing else.

`proxy_url()` is for clients that take a proxy as an argument instead.
"""

import os

from epicstaff_plugin.contracts.runtime import HTTPS_PROXY_ENVIRONMENT_VARIABLE


class EgressProxyUnavailable(Exception):  # noqa: N818 (named like DatabaseUnavailable)
    """`HTTPS_PROXY` is not set: the process runs off the plugin node."""


def proxy_url() -> str:
    """Return the egress proxy's URL, with this plugin's credentials in it.

    It holds the plugin's proxy password: never log it or show it.

    Raises:
        EgressProxyUnavailable: `HTTPS_PROXY` is not set.
    """
    value = os.environ.get(HTTPS_PROXY_ENVIRONMENT_VARIABLE)
    if not value:
        raise EgressProxyUnavailable(
            f"{HTTPS_PROXY_ENVIRONMENT_VARIABLE} is not set; the EpicStaff node sets it for "
            "every plugin backend"
        )
    return value
