# Develop a plugin locally

Run EpicStaff with the plugin platform on your machine, install your plugin, and check it in real browsers.

## Host names

| What | Address |
|---|---|
| EpicStaff | `http://epicstaff.localhost` |
| A plugin | `http://<id>.plugins.epicstaff.localhost` |

with `DJANGO_FRONTEND_BASE_URL=http://epicstaff.localhost`, `PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost` and
`DJANGO_REFRESH_COOKIE_SECURE=false`; [Enable the plugin platform](../operator/enable-plugins.md) has the rest.

Chromium and Firefox resolve every `*.localhost` name to your machine by themselves. Safari uses the operating system's
resolver, which on current macOS does the same.

EpicStaff and its plugin hosts must share a registrable domain (`epicstaff.localhost` here): the sign-in inside
EpicStaff's frame relies on EpicStaff's session cookie being sent to EpicStaff from the plugin's frame, which browsers
allow only between hosts of the same site. Plain `localhost` for EpicStaff with `plugins.localhost` for plugins does
not work: those are two sites.

## Secure context

Signing in needs the Web Crypto API, which browsers offer only in a **secure context**: `https`, or plain `http` on
`localhost` and `*.localhost`. On any other plain `http` address (`http://weather.plugins.epicstaff.test`, a LAN IP)
`createPluginLogin` throws `insecure_context`.

## Safari

Test Safari against `*.test` names over HTTPS, or on a real domain:

1. Add `epicstaff.test` and `<id>.plugins.epicstaff.test` to `/etc/hosts` (pointing at `127.0.0.1`).
2. Make a local certificate authority and a wildcard certificate for `epicstaff.test` and `*.plugins.epicstaff.test`,
   trust the authority in your keychain, and run nginx with `NGINX_SSL_MODE=on`.
3. Set `DJANGO_FRONTEND_BASE_URL=https://epicstaff.test`, `PLUGINS_BASE_DOMAIN=plugins.epicstaff.test` and
   `DJANGO_REFRESH_COOKIE_SECURE=true`.

`http://*.test` is not a secure context, so the SDK refuses it.

## Build and install the Weather sample

```bash
npm --prefix plugin-sdk ci && npm --prefix plugin-sdk run build
npm --prefix plugin-samples/weather/spa ci && npm --prefix plugin-samples/weather/spa run build
```

then pack, sign and install it as [Sign and package a plugin](sign-and-package.md) describes, approve it, and grant it
to an organization.

## Tests

| What | Command |
|---|---|
| The JS SDK and the platform callback pages (Node, no browser) | `npm --prefix plugin-sdk test` |
| The Weather page (type check and build) | `npm --prefix plugin-samples/weather/spa run build` |
| Sign-in and popups in Chromium, Firefox and WebKit, against your running stack | below |

The browser checks in `plugin-sdk/test-browser/` sign a person in inside EpicStaff and on the plugin's own address,
renew, end the session, and run both popup paths, against the Weather sample. They need a running stack with Weather
installed, approved, running and granted to two organizations, A and C, and one person who is a member of both with
View on Weather:

```bash
npm --prefix plugin-sdk/test-browser ci
npx --prefix plugin-sdk/test-browser playwright install chromium firefox webkit
E2E_EMAIL=ada@acme.test E2E_PASSWORD='…' \
E2E_ORG_A_ID=3 E2E_ORG_A_NAME=Acme E2E_ORG_C_ID=5 E2E_ORG_C_NAME=Cobalt \
    npm --prefix plugin-sdk/test-browser run e2e
```

| Variable | Default |
|---|---|
| `E2E_EPICSTAFF_URL` | `http://epicstaff.localhost` |
| `E2E_PLUGIN` | `weather` |
| `E2E_PLUGIN_URL` | `http://weather.plugins.epicstaff.localhost` |
| `E2E_EMAIL`, `E2E_PASSWORD` | Required: the person above |
| `E2E_ORG_A_ID`, `E2E_ORG_A_NAME`, `E2E_ORG_C_ID`, `E2E_ORG_C_NAME` | Required: the two organizations |

Add `--project=webkit` (or `chromium`, `firefox`) to run one engine. They do not run in CI. Against the HTTPS stack of
[Safari](#safari), set `E2E_EPICSTAFF_URL=https://epicstaff.test` and
`E2E_PLUGIN_URL=https://weather.plugins.epicstaff.test`; the browsers accept its local certificate.

### Login and refresh rates

The suite signs the person in seven times per browser, 21 times for a run of all three, and every EpicStaff page it
opens renews EpicStaff's session, all from your address within a minute. EpicStaff's default throttles
(`DJANGO_LOGIN_THROTTLE_RATE=5/min`, `DJANGO_LOGIN_IP_THROTTLE_RATE=20/min`, `DJANGO_TOKEN_REFRESH_THROTTLE_RATE=30/min`)
stop a run part-way: a test then waits on a login form that says "Too many login attempts" until it times out. On
your local stack only, raise them in `src/.env`:

```bash
DJANGO_LOGIN_THROTTLE_RATE=100/min
DJANGO_LOGIN_IP_THROTTLE_RATE=300/min
DJANGO_TOKEN_REFRESH_THROTTLE_RATE=600/min
```

and recreate django_app, which reads them only when it starts (from `src/`):

```bash
docker compose -f docker-compose.yaml --env-file ./.env up -d django_app
```

Each test signs in for itself instead of reusing a saved browser state: EpicStaff replaces the refresh cookie at every
renewal and refuses the old one, so a saved state is signed out once the first test has used it.
