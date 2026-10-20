# Enable the plugin platform

Plugins add pages to EpicStaff. A SuperAdmin uploads a plugin package, reviews it, approves it and
grants it to organizations; members of those organizations then find the plugin in the left bar.
Each plugin is served from its own host name, `<identifier>.<PLUGINS_BASE_DOMAIN>` (for example
`weather.plugins.example.com`), and shown inside EpicStaff in a frame. This page is what an
operator sets up for that. How to build and sign a package is in [the plugin docs](../README.md).

In this version plugins are web pages only: nginx serves their files, and they need no extra
containers.

## Before you start

- **HTTPS.** The plugin platform runs only over HTTPS. Plain http is allowed only for local
  development on `*.localhost` names, and EpicStaff refuses to start otherwise (see
  [What stops at start-up](#what-stops-at-start-up)).
- **A domain name.** EpicStaff must be reached by a domain name; a deployment reached by an IP
  address cannot use plugins.
- **One wildcard DNS record**, `*.plugins.example.com`, pointing at the same address as EpicStaff.
- **One wildcard TLS certificate** for `*.plugins.example.com`. Let's Encrypt issues wildcard
  certificates only through the DNS-01 challenge.
- **A base domain you will keep.** Every plugin's address is built from it. Browsers keep each
  plugin's data under its address, and plugins may register their address with outside services
  (for example as an OAuth callback). Changing the base domain later breaks all of that.

## 1. DNS

Add one record, `*.plugins.example.com`, with the same target as EpicStaff's own name (an `A`/`AAAA`
record, or a `CNAME` to EpicStaff's name). No record per plugin is needed.

## 2. Certificate

Put the wildcard certificate and its key next to EpicStaff's own (see [SSL](../../setup/ssl.md)):

```
src/nginx/certs/plugins-fullchain.pem   # certificate for *.plugins.example.com
src/nginx/certs/plugins-privkey.pem     # its private key
```

With `NGINX_SSL_MODE="on"` and plugins on, nginx does not start without these two files. After a
renewal, reload nginx: `docker compose exec epicstaff-nginx nginx -s reload`.

A self-signed wildcard certificate for testing, from the repo root (replace the domain):

```bash
docker run --rm -v "$(pwd)/src/nginx/certs:/certs" -w /certs alpine \
  sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout plugins-privkey.pem -out plugins-fullchain.pem \
    -subj '/CN=*.plugins.example.com' -addext 'subjectAltName=DNS:*.plugins.example.com'"
```

## 3. Settings

Set these in `src/.env`. `src/env.yaml` holds the full descriptions and the defaults.

| Variable | Default | What to set |
|---|---|---|
| `PLUGINS_ENABLED` | `false` | `true` turns on the plugin API in Django, the plugin hosts and the upload route in nginx, and the plugin pages in the UI. The same spellings as `CHAT_ENABLED` are accepted. |
| `PLUGINS_BASE_DOMAIN` | `plugins.invalid` (production), `plugins.epicstaff.localhost` (development) | The parent of every plugin host, in lower case: `plugins.example.com`. The production default is a placeholder that EpicStaff refuses with plugins on. |
| `PLUGINS_TRUSTED_SIGNING_KEYS` | `none` | The publishers you trust, comma-separated `<name>:<minisign public key>`. Packages signed by one of these keys are shown as Trusted; see [trust and signing](../explanation/trust-and-signing.md). |
| `PLUGINS_MAX_PACKAGE_MB` | `300` | The largest package an upload may carry, in MiB (1 MiB = 1,048,576 bytes). Django applies it to the package; nginx accepts a request body one MiB larger, for the multipart framing. Before nginx reads any of an upload, it asks Django (without the body) whether the caller is a logged-in SuperAdmin, and refuses everyone else with 401 or 403, so nobody else can make EpicStaff store a large body. A proxy in front of EpicStaff must allow that size too. |
| `PLUGINS_STORAGE_BUCKET` | `epicstaff-plugins` | The bucket in EpicStaff's storage that keeps uploaded packages. Created on the first upload. |
| `DJANGO_FRONTEND_BASE_URL` | already set | The exact origin people open EpicStaff at, such as `https://epicstaff.example.com`: scheme, host and port only, no path (a trailing `/` is allowed). Only this origin may frame a plugin page, so any other value (the development default `http://localhost:4200`, a different port) leaves every plugin page blank. |
| `DJANGO_REFRESH_COOKIE_SECURE` | already set | `true` on HTTPS. |
| `DJANGO_ALLOWED_HOSTS` | already set | Only if you restrict it (the default is `*`): add `.plugins.example.com`. Each plugin host fetches its configuration from Django under its own host name. |

## 4. Apply

`restart` does not re-read `src/.env`; recreate the three containers that read the settings:

```bash
cd src
docker compose -f docker-compose.yaml --env-file ./.env up -d django_app epicstaff-nginx frontend
```

The frontend writes its `config.json` when it starts. If you mount your own `config.json` instead,
add `"isPluginsEnabled": true` to it.

## What stops at start-up

Wrong values stop a container with a message instead of serving a broken plugin page.

**django_app** (Django system checks, only with plugins on):

| Check | Fails when |
|---|---|
| `plugins.E001` | `DJANGO_REFRESH_COOKIE_SECURE` is false and `PLUGINS_BASE_DOMAIN` does not end in `.localhost`. Over plain http a plugin page could plant cookies that EpicStaff would trust. |
| `plugins.E002` | `PLUGINS_BASE_DOMAIN` is not a lower-case DNS name, or ends in `.invalid`. |
| `plugins.E003` | `DJANGO_FRONTEND_BASE_URL` is not an `http://` or `https://` origin with a host name (letters, digits and hyphens, not an IP address) and an optional port (anything after the host and port but a trailing `/` counts as not an origin), or is `http://` on a host that does not end in `.localhost`. |
| `plugins.E004` | An entry of `PLUGINS_TRUSTED_SIGNING_KEYS` is not `<name>:<public key>`, or two entries have the same name or the same public key. |
| `plugins.E005` | `DJANGO_CORS_ALLOWED_ORIGINS` lists a plugin host (`PLUGINS_BASE_DOMAIN` or a name under it). Cross-origin calls to EpicStaff carry the person's login, so a plugin page must never be allowed one. |

**epicstaff-nginx** exits with an `ERROR:` line when `PLUGINS_ENABLED` is not a boolean, and, with
plugins on, when `PLUGINS_BASE_DOMAIN` is not a lower-case DNS name of two or more labels,
`DJANGO_FRONTEND_BASE_URL` is not `http(s)://<host>[:<port>]` with at most a trailing `/` (a
path, query or fragment is refused, as Django's `plugins.E003` does), or `PLUGINS_MAX_PACKAGE_MB`
is not a whole number of MiB above 0. With plugins off nginx does not read the
plugin values at all.

**frontend** exits when `PLUGINS_ENABLED` is not a boolean.

## Check it

After a SuperAdmin has approved one plugin, check nginx's plugin routes from any machine that
reaches EpicStaff:

```bash
EPICSTAFF_URL=https://epicstaff.example.com PLUGINS_BASE_DOMAIN=plugins.example.com \
PLUGIN_IDENTIFIER=weather PLUGINS_MAX_PACKAGE_MB=300 bash src/nginx/tests/plugins_smoke.sh
```

It prints one `ok` or `not ok` line per check. Extra arguments are passed to every curl call, for
example `--insecure` for a self-signed certificate. With `SMOKE_ADMIN_TOKEN` set to a SuperAdmin's access
token it also streams a 51 MiB upload to Django.

If you change the nginx templates, `bash src/nginx/tests/check_templates.sh` renders them with
every combination of settings and runs `nginx -t` on each (needs Docker and `openssl`).

## Local development

| Variable | Value |
|---|---|
| `PLUGINS_ENABLED` | `true` |
| `PLUGINS_BASE_DOMAIN` | `plugins.epicstaff.localhost` |
| `NGINX_SERVER_NAME` | `epicstaff.localhost` |
| `NGINX_SSL_MODE` | `off` |
| `DJANGO_FRONTEND_BASE_URL` | `http://epicstaff.localhost` |
| `DJANGO_REFRESH_COOKIE_SECURE` | `false` |

Open EpicStaff at `http://epicstaff.localhost`, not `http://localhost`: a plugin at
`http://weather.plugins.epicstaff.localhost` must be a subdomain of EpicStaff's own name. Chrome and
Firefox send every `*.localhost` name to your machine without DNS; other tools may need one
`/etc/hosts` line per name. Safari treats `*.localhost` names differently, so test Safari against
a real domain over HTTPS.

## Where plugin data lives

| What | Where |
|---|---|
| Uploaded packages | The `PLUGINS_STORAGE_BUCKET` bucket in EpicStaff's storage |
| Approved plugins' web files, as served | The `plugin_spa` Docker volume: django_app writes it, epicstaff-nginx reads it |
| Plugins, approvals and grants | EpicStaff's database |

Back up the `plugin_spa` volume with the bucket and the database.

## Turning plugins off

Set `PLUGINS_ENABLED=false` and recreate the same three containers. Plugin host names then reach
EpicStaff's own pages, the plugin API answers 404 and the plugins leave the left bar. Nothing is
deleted: packages, approvals, grants and published files stay, and come back when you turn the
platform on again.

## Behind another proxy or load balancer

If TLS ends in front of EpicStaff, route `*.plugins.example.com` to EpicStaff's nginx as well, keep
the `Host` header, allow request bodies of `PLUGINS_MAX_PACKAGE_MB` plus one MiB on
`/api/admin/plugins/packages/`, and put the wildcard certificate on that proxy. Then set `NGINX_SSL_MODE=off` and `DJANGO_REFRESH_COOKIE_SECURE=true`.

The `epicstaff-nginx` service sets the `net.ipv4.tcp_tw_reuse` sysctl for its own container (no
extra privileges). It lets nginx reuse closed connections' local ports, so a busy proxied route
does not run out of them and start answering 502.
