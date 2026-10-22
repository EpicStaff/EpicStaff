# JS SDK (`@epicstaff/plugin-sdk`)

The browser package for plugin pages, in the EpicStaff repository at `plugin-sdk/`. It loads the platform config,
speaks the [frame protocol](frame-protocol.md) with EpicStaff, signs the person in through EpicStaff, sends their token
to the plugin's own API, and hands an external provider's popup result back to the page. It has no dependencies and
runs in every current browser.

| Export | What it is for |
|---|---|
| `startPlugin` | Start-up: the `es_org` hint, the platform config, the frame handshake, theme and address sync |
| `createPluginLogin` | Sign-in through EpicStaff, renewal, and `fetch` for the plugin's own API |
| `createPopupState`, `PluginLogin.openPopup`, `PluginLogin.completePopup` | An external provider's sign-in in a popup; see [External callbacks](../how-to/external-callbacks.md) |
| `loadPlatformConfig`, `parsePlatformConfig` | The platform config on its own |
| `LOGIN_*`, `FRAME_*`, `THEME_*`, `AVAILABILITY_STATES` constants | The protocol values, equal to `contracts/login-protocol.json` and `contracts/frame-protocol.json` |
| `GATEWAY_DENY_HEADER`, `GATEWAY_DENY_REASONS`, `gatewayRefusal` | The header that marks a [refusal by EpicStaff's gateway](#gateway-refusals), its values, and reading one from a response |

Until the package is published, a plugin takes it from the repository (`"@epicstaff/plugin-sdk":
"file:<path to>/plugin-sdk"`), as the [Weather sample](../../../plugin-samples/weather/spa/) does.

## Start-up

```ts
import { createPluginLogin, startPlugin } from '@epicstaff/plugin-sdk';

// Before the router starts: removes es_org from the address and captures the first navigation.
const plugin = await startPlugin({ routing: 'pathname' });

const login = createPluginLogin(plugin);
login.onChange(render);
render();
await login.start();
```

`startPlugin` is described in [Frame protocol](frame-protocol.md#using-the-js-sdk). It works the same inside EpicStaff
and on the plugin's own address. Sign-in is separate: it is not part of the frame protocol, and it works without it.

## Sign-in

A person signs in to a plugin **through EpicStaff**: the plugin never sees a password, an EpicStaff cookie or an
EpicStaff token. It gets a **plugin login token**: valid for 15 minutes, for one person in one organization and for
this plugin only, accepted only by EpicStaff's gateway in front of the plugin's own `/api/`. The plugin's backend never
receives the token either; it receives a signed [gateway context](gateway-context.md) instead.

Only a plugin with a backend can sign people in: for a frontend-only plugin the platform config has `"login": null`.

### `createPluginLogin(plugin, options?)`

Prepares the sign-in; nothing happens until `start()`. `plugin` is what `startPlugin` returned.

| Option | Default | Meaning |
|---|---|---|
| `window` | the global `window` | The window `startPlugin` was given |
| `fetch` | the global `fetch` | Used for the token exchange and for `login.fetch` |

It throws `PluginLoginError` with `code`:

- `insecure_context`: the page is not a [secure context](../how-to/local-development.md#secure-context), so the Web
  Crypto API that PKCE needs is missing. Plain `http` is a secure context only on `localhost` and `*.localhost`.
- `login_unavailable`: the platform config has `"login": null`.

### `PluginLogin`

| Member | Meaning |
|---|---|
| `state` | Where the sign-in stands; see below |
| `session` | `{plugin, org, user, permissions, expiresAt}` while `state` is `signed-in`, else `null`. `permissions` are the person's actions on the plugin in this organization, in manifest order, always with `read`. `expiresAt` is in milliseconds since the epoch, by the browser's clock |
| `error` | A `PluginLoginError` while `state` is `failed`, else `null` |
| `availability` | Whether the plugin's API can be reached: `available`, `maintenance` or `unavailable`; see [Availability](#availability) |
| `onChange(listener)` | Calls `listener(state)` on every state change and on every renewed token. Returns the function that stops it |
| `onAvailabilityChange(listener)` | Calls `listener(availability)` on every change of `availability`. Returns the function that stops it |
| `start()` | Signs the person in (below). Resolves with the state it reached. Runs once; later calls share the first |
| `renew()` | Gets a new token for the same organization, silently. Never navigates |
| `signIn()` | Sends the page to EpicStaff to sign in, and back to the same address. For a "Sign in again" button |
| `fetch(input, init?)` | `fetch` for the plugin's own API; see below |
| `openPopup(url, options)` | See [External callbacks](../how-to/external-callbacks.md) |
| `completePopup(options?)` | See [External callbacks](../how-to/external-callbacks.md) |
| `close()` | Stops renewals, removes the hidden frame, and rejects a pending `openPopup` with `closed` |

| `state` | Meaning | What the page shows |
|---|---|---|
| `idle` | `start()` has not run | Nothing yet |
| `signing-in` | Signing in, or on the way to EpicStaff to sign in | "Signing in…" |
| `signed-in` | There is a token | The page |
| `access-denied` | The person may not use the plugin in this organization (or in any of theirs). Also after the gateway refuses the person (`403` with `X-EpicStaff-Gateway-Deny: forbidden`) | "You do not have access to … in this organization" |
| `session-ended` | The EpicStaff session ended while the page was open (a renewal got `login_required`) | Inside EpicStaff: "Sign in again" (`signIn()`). On its own address the SDK goes to EpicStaff's login at once |
| `maintenance` | The plugin is being updated in the person's organization, so EpicStaff signs nobody in to it there for now (the authorize step answered `temporarily_unavailable`). `availability` is `maintenance` too | "… is being updated. It will be back in a few minutes.", and `renew()` now and then (every 30 seconds) to try again |
| `failed` | Something unexpected: the token endpoint refused the code or could not be reached, or an answer was malformed. `error` says what | The message and "Try again" (`signIn()`) |

### What `start()` does

1. **A sign-in that just came back.** When the platform callback page left an answer in `sessionStorage` for the
   sign-in this tab started, `start()` takes it (and removes it), checks its `state`, and exchanges the code.
2. **Silently.** Otherwise it loads EpicStaff's authorize endpoint with `prompt=none` in a hidden frame. EpicStaff
   answers on the plugin's own `/.well-known/epicstaff/silent-callback.html`, which posts the answer to the page. Only a
   message from that frame, from the page's own origin, with the same `state`, counts; no answer within 10 seconds
   counts as `login_required`. A code means the person is signed in with no visible change.
3. **Interactively.** On `login_required` (no EpicStaff session) or `interaction_required` (more than one organization
   to choose from) the page is **replaced** by the authorize endpoint. EpicStaff shows its login form or its
   organization chooser, then answers on `/.well-known/epicstaff/callback.html`, which stores the answer and returns to
   the page's address (path, query and fragment). `start()` then finishes step 1.
4. `access_denied` at any step is the `access-denied` state, without navigating.
5. `temporarily_unavailable` at any step is the `maintenance` state, without navigating: the page does not loop
   through EpicStaff's login while the plugin is updated. A later `renew()` that gets a code signs the person in and
   ends the maintenance; one that ends in `access-denied`, `session-ended` or `failed` ends it too (an organization
   whose upgrade failed for good gets no access).

Every navigation is a `location.replace`: inside EpicStaff a frame navigation would otherwise add entries to
EpicStaff's history, and Back would step through the sign-in instead of leaving the plugin.

**Organization.** Inside EpicStaff the page signs in to the organization EpicStaff opened it in (the `es_org` hint);
when EpicStaff refuses it, the state is `access-denied`. On its own address it signs in to the organization of the last
token in this tab, and without one EpicStaff asks. When EpicStaff refuses that remembered organization (the person lost
access there), the SDK forgets it and signs in again without one: EpicStaff takes the person's only organization, or
asks. When the person switches organization in EpicStaff, EpicStaff reloads the frame with the new `es_org`, and the
page signs in again.

**Renewal.** 60 seconds before the token expires the SDK renews it silently, for the same organization. `renew()`
does the same at once. Browsers hold timers back in background tabs and while the computer sleeps, so a token can
fall due unnoticed: `fetch` then renews before it sends, and so does showing the tab again.

**PKCE and state.** Each sign-in has a new verifier (32 random bytes, base64url), its S256 challenge (RFC 7636) and a
new `state` (32 random bytes). The verifier never leaves the page except to the token endpoint.

**Where things are kept.** The token lives in memory only, never in any storage. `sessionStorage` on the plugin's
origin holds the sign-in under way (`epicstaff.login.pending`: `state`, verifier, return address, organization,
creation time; ignored after 10 minutes), the callback page's answer (`epicstaff.login.result`, for a moment), and the
organization id of the last token (`epicstaff.login.org`).

### `login.fetch(input, init?)`

```ts
const response = await login.fetch('/api/whoami');
```

- `input` is resolved against the page's origin.
- `Authorization: Bearer <token>` is added **only** when the URL is on the page's own origin and its path is at or
  below `api_base` from the platform config (`/api/`): not `/apix`, not `/.well-known/`, never another origin.
  EpicStaff's API refuses the token anyway; the rule keeps it from leaking anywhere else.
- A request made while a sign-in or renewal is under way waits for it; one made when the token is within 60 seconds of
  expiry renews first.
- Only refusals by EpicStaff's gateway change the sign-in; see [Gateway refusals](#gateway-refusals) below:
  - `401` with `X-EpicStaff-Gateway-Deny: login` (the gateway no longer accepts the token): it renews once and
    retries once. If the renewal ends the session, the original response is returned.
  - `403` with `X-EpicStaff-Gateway-Deny: forbidden` (the token is fine, but the person may no longer use the
    plugin): the state becomes `access-denied`; no retry.
- A `503` from the gateway with `maintenance` or `unavailable` sets [`availability`](#availability), is returned as it
  is, and never renews.
- Every other response, including your backend's own `401` and `403` whatever their body says, is returned as it is
  and changes nothing.
- A request that may be retried must have a body that can be sent twice (a string, `Blob`, `FormData`, …, not a
  stream). A stream body is never retried.

### Gateway refusals

Every refusal the gateway answers itself, before your backend sees the request, carries the response header
`X-EpicStaff-Gateway-Deny` (exported as `GATEWAY_DENY_HEADER`), with EpicStaff's JSON error body:

| Status | `X-EpicStaff-Gateway-Deny` | `code` in the body | Meaning |
|---|---|---|---|
| 401 | `login` | `login_required` | No token, or one the gateway no longer accepts |
| 403 | `forbidden` | `forbidden` | The person may no longer use the plugin in this organization. Membership is checked first: a person removed from the organization gets this, whatever state the plugin is in there, and never `maintenance` |
| 404 | `not_found` | `not_found` | Not a path the gateway forwards |
| 413 | `too_large` | `request_too_large` | The body is over the limit |
| 429 | `rate_limited` | `rate_limited` | A public path's rate limit |
| 503 | `unavailable` | `plugin_unavailable` | The plugin's process is not running or not answering, or the person's organization could not be upgraded |
| 503 | `maintenance` | `plugin_maintenance` | The plugin is being updated, on every path, public ones included; or the person's organization still is |

The `503` answers carry `Retry-After` (seconds). The gateway removes the header from your backend's responses, so your
backend cannot fake a gateway refusal, and its own `401` and `403` never end or renew the sign-in. The page reads the
header without any CORS setting: the request goes to the page's own origin.

`gatewayRefusal(response)` reads a refusal from any response, for requests your page sends with its own `fetch`:

```ts
const refusal = gatewayRefusal(response); // { reason: 'maintenance', retryAfterSeconds: 30 }, or null
```

It is `null` for a response that passed the gateway, and for a reason this version of the SDK does not know.
`retryAfterSeconds` is `null` when `Retry-After` is not a whole number of seconds.

### Availability

`login.availability` follows the answers `login.fetch` gets from the plugin's own API:

| Answer | `availability` |
|---|---|
| `503` with `X-EpicStaff-Gateway-Deny: maintenance` | `maintenance` |
| `503` with `X-EpicStaff-Gateway-Deny: unavailable` | `unavailable` |
| Any response without the header (it passed the gateway), your backend's own `503` included | `available` |
| The gateway's other refusals (`login`, `forbidden`, `not_found`, `too_large`, `rate_limited`) | Unchanged |

Sign-in results change it too. The API's answers stay the source: a sign-in result never ends a `maintenance` the
API answered, except a sign-in that gets a token.

| Sign-in result | `availability` |
|---|---|
| `temporarily_unavailable` (the `maintenance` state) | `maintenance`. When the API had answered `maintenance` already, it stays the API's |
| A token (`signed-in`) | `available` when it was `maintenance`; `unavailable` stays |
| `access-denied`, `session-ended` or `failed` | `available` when a sign-in had set `maintenance`; a `maintenance` the API answered, and `unavailable`, stay |

It starts as `available`.

**Inside EpicStaff** you need not show anything for it: on a change to `maintenance` or `unavailable` the SDK tells
EpicStaff with the frame message [`availability.changed`](frame-protocol.md#messages), at most once every 30 seconds
(a change inside that window is sent when it ends). EpicStaff then asks its own server and shows its maintenance panel,
or "not available", instead of your page. `plugin.reportAvailability(state)` sends the same message for a page that
calls its API without `login.fetch`; it does nothing unframed.

**On its own address** the page decides: show "… is being updated. It will be back in a few minutes." while
`availability` is `maintenance` and the sign-in was not denied, ended or failed (show that instead), and check again
every 30 seconds (`Retry-After`). While the plugin itself is being
updated, the gateway answers the page's own address with EpicStaff's maintenance page, so a page loaded now sees it
only through its API; a page already open sees it through `availability`.

```ts
login.onAvailabilityChange(render);

async function checkAgain(): Promise<void> {
    if (login.state === 'maintenance') await login.renew(); // the sign-in was refused while the update runs
    if (login.state === 'signed-in') await login.fetch('/api/whoami'); // any route behind the sign-in
}
```

Ask a route behind the sign-in, not a public one: a public path answers as soon as the plugin runs, while the person's
organization may still be being upgraded.

## Errors

`PluginLoginError` has a `code`:

| `code` | Raised by | Meaning |
|---|---|---|
| `insecure_context` | `createPluginLogin` | Not a secure context |
| `login_unavailable` | `createPluginLogin` | `"login": null` |
| `storage_unavailable` | sign-in, `completePopup` | `sessionStorage` is blocked, so an interactive sign-in cannot return |
| `callback_failed` | sign-in | The callback page brought back nothing usable |
| `exchange_failed` | sign-in | The token endpoint refused the code (the message names its error code) or could not be reached |
| `invalid_token_response` | sign-in | The token endpoint's answer was not a plugin login token for this plugin |
| `invalid_popup_state` | `createPopupState`, `openPopup` | Not `<org id>.<random>` |
| `invalid_popup_url` | `openPopup` | Not an `http:` or `https:` address |
| `popup_blocked` | `openPopup` | The browser blocked the popup |
| `popup_timeout` | `openPopup` | No result within 10 minutes |
| `relay_failed` | `completePopup` | The plugin's relay refused the parameters |
| `closed` | `openPopup` | `close()` was called |

Errors from EpicStaff's endpoints themselves are listed in [Error codes](error-codes.md).

## Platform config

```json
{
    "plugin": { "identifier": "weather", "name": "Weather", "version": "0.3.0" },
    "epicstaff_origin": "https://epicstaff.example.com",
    "frame_protocol": 1,
    "api_base": "/api/",
    "login": {
        "authorize_url": "https://epicstaff.example.com/api/auth/plugin-authorize/",
        "token_url": "https://epicstaff.example.com/api/auth/plugin-token/"
    }
}
```

`parsePlatformConfig` refuses a `login` whose URLs are not on `epicstaff_origin`, or carry a query or a fragment.

## Behind a development server

The SDK works unchanged while EpicStaff serves your page from a development server on your machine (development mode,
[Local development](../how-to/local-development.md#develop-the-page-against-a-development-server)). The page still
runs on the plugin's own origin, inside the same frame, so the frame handshake, the sign-in and
`/.well-known/epicstaff/config.json` are the same as for the published page: there is no option to set and no other
address to allow. Your `/api/` calls go through the gateway as always, to the installed backend or to a development
backend, whichever EpicStaff routes them to. A live reload is a new page load: `startPlugin` and `login.start()` run
again and sign the person in silently.

## The protocol, for a page without the SDK

The values are in [`plugin-sdk/contracts/login-protocol.json`](../../../plugin-sdk/contracts/login-protocol.json).

| Step | Request |
|---|---|
| Authorize (a navigation, never `fetch`) | `GET <authorize_url>?plugin=<id>&state=<state>&code_challenge=<challenge>&code_challenge_method=S256[&org=<id>][&prompt=none]`. No other parameter is accepted |
| Answer | A redirect to `<plugin origin>/.well-known/epicstaff/callback.html` (or `silent-callback.html` with `prompt=none`) with `#code=<code>&state=<state>`, or `#error=login_required|access_denied|interaction_required&state=<state>` |
| Exchange (cross-origin, within 60 seconds, once) | `POST <token_url>`, `Content-Type: application/json`, `credentials: 'omit'`, body `{"code", "code_verifier"}` |
| Token | `200 {"access_token", "token_type": "Bearer", "expires_in": 900, "plugin": {"identifier", "version"}, "org": {"id", "name"}, "user": {"id", "email", "name"}, "plugin_permissions": [...]}` |

The platform callback pages belong to EpicStaff and are the same on every plugin host. A page that does not use the
SDK must keep `sessionStorage['epicstaff.login.pending']` in the SDK's shape for `callback.html` to return to it.
