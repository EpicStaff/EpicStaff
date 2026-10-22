# Call the internet from your backend

A plugin backend has no direct route to the internet. Everything it sends out goes through the
deployment's **egress proxy**, which lets through HTTPS on port 443 to the hosts the plugin's
manifest declares, and refuses everything else. This page shows how to declare hosts, how your
HTTP client reaches them, and what a refusal looks like. Part 3 of the
[tutorial](../tutorial/build-your-first-plugin.md#part-3-search-through-an-outbound-host) walks
through the Weather sample's.

## 1. Declare the hosts

```json
"outbound_hosts": [
    { "host": "geocoding-api.open-meteo.com", "reason": "Looks up places by name when someone adds a saved place." },
    { "host": "*.example-cdn.com", "reason": "Downloads map tiles." }
]
```

- `host` is a lower-case DNS name: no IP address, no port, no scheme. At most 100 hosts, each
  once ([Manifest](../reference/manifest.md)). Needs `backend`.
- **Exact names** match only themselves.
- **`*.` wildcards** match every name below the domain, at any depth: `*.example-cdn.com`
  matches `tiles.example-cdn.com` and `a.b.example-cdn.com`, but not `example-cdn.com` itself
  (list it separately if you need it) and not `otherexample-cdn.com`.
- `reason` (1–200 characters) says why. The SuperAdmin reads every host and reason before
  approving the package, and the review warns about each wildcard. Org Admins see them on your
  plugin's card in Settings → Plugin activity, and the Runtime tab lists them under **Outbound
  access**.

Outbound access belongs to the plugin, not to an organization: suspending the plugin in one
organization leaves it as it is.

## 2. Use a client that reads the environment

The node puts the proxy's address, with your plugin's own credentials, in the backend's
environment, and keeps EpicStaff's internal API and loopback direct
([Runtime](../reference/runtime.md#environment)):

| Variable | Value |
|---|---|
| `HTTPS_PROXY`, `https_proxy`, `HTTP_PROXY`, `http_proxy` | `http://<id>:<password>@plugins_egress:3128` |
| `NO_PROXY`, `no_proxy` | The host of EpicStaff's API, then `localhost,127.0.0.1,::1` |

Most clients use them with no code:

| Client | What to do |
|---|---|
| httpx | Nothing: `trust_env=True` is its default. Don't turn it off on a client that calls the internet |
| requests | Nothing: it reads the environment by default |
| `urllib.request` | Nothing: it reads the environment by default |
| aiohttp | `aiohttp.ClientSession(trust_env=True)` |
| curl, in a subprocess | Nothing: it reads the lower-case `https_proxy` |
| Anything that takes a proxy as an argument | `epicstaff_plugin.egress.proxy_url()` returns `HTTPS_PROXY` ([Python SDK](../reference/python-sdk.md#epicstaff_pluginegress)) |

The proxy URL holds your plugin's proxy password: never log it, show it, or put it on a command
line. The SDK's EpicStaff client never uses the proxy, whatever the environment says.

The proxy only tunnels: your client opens TLS to the host itself, through the tunnel, and checks
the host's certificate as usual. The proxy sees the host name and port, never what you send.

## When the proxy refuses

| What the backend tried | The proxy answers | `X-Squid-Error` |
|---|---|---|
| A host the manifest does not list, an IPv4 or IPv6 address included (an address is never on the list) | `403` to the tunnel (`CONNECT`) | `ERR_HOST_NOT_ALLOWED` |
| A listed host on a port other than 443 | `403` to the tunnel | `ERR_PORT_NOT_ALLOWED` |
| Plain `http://`, to any host | `403` to the request | `ERR_ONLY_CONNECT` |
| A listed host whose address is private, loopback, link-local or otherwise reserved | `403` | `ERR_PRIVATE_DST` |
| A listed host that has only IPv6 addresses: the proxy runs with IPv6 off | `503` | `ERR_DNS_FAIL` |
| Wrong proxy credentials, or none | `407` | — |
| Going around the proxy | No answer: name resolution fails for every outside name, and there is no route out | — |

A refused tunnel is an exception in most clients, for example `httpx.ProxyError: 403 Forbidden`
or `requests.exceptions.ProxyError`. A refused plain `http://` request is an ordinary `403`
response. `curl -v` shows the `X-Squid-Error` header in both cases.

The proxy logs every request with your plugin's id, the host and port, and the result, never
your credentials.

## How long changes take

The node issues the proxy credentials when it starts your backend, and keeps them across its
restarts. Once the backend stops for good, or a host leaves the list, the proxy refuses it
within about 30 seconds.

## What an allow-list does not stop

- **Domain fronting.** The proxy checks the host name your client asks it to connect to, not
  what travels inside the TLS connection. A host on a content delivery network that serves many
  sites can be asked, inside TLS, for another of those sites. So `outbound_hosts` limits which
  servers your backend connects to, not which sites those servers answer for.
- **Flows and tools run code elsewhere.** A plugin whose `access` includes `flows` `create`,
  `update` or `use`, or `tools` `create` or `update`, can have code of its choosing run in
  EpicStaff's sandbox. That sandbox has its own network access, and `outbound_hosts` do not
  apply to that code. `tools` `create` or `update` also lets the plugin point an agent at an MCP
  server outside `outbound_hosts`.
- **Wildcards widen it.** `*.example-cdn.com` allows every name below it, including ones made
  later by whoever controls the domain. Prefer exact names, and keep wildcards to domains you
  trust.

A SuperAdmin reviewing a plugin should read a host on a large shared network, and every wildcard,
as access to more than its name.

## On your machine

Off the plugin node there is no egress proxy and no proxy variables: your client connects
directly, and nothing refuses an undeclared host. Check that every host your backend calls is in
`outbound_hosts` before you upload.
