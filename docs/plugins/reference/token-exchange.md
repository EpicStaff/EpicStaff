# Token exchange: how a person logs in to a plugin

A plugin's page calls its own backend (`https://<id>.<plugins base domain>/api/**`) as the person
using EpicStaff. To do that it needs a **plugin login token**, which it gets from EpicStaff
without ever seeing the person's password or EpicStaff's own session. The [JS SDK](js-sdk.md)
runs this whole exchange for you; this page describes what happens underneath, for reviewers,
for debugging, and for anyone writing a client without the SDK.

The exchange is OAuth 2.0's authorization code flow for a public client with PKCE (RFC 7636,
method `S256`), with two EpicStaff rules on top:

- the code is handed only to the plugin's own callback page, at a fixed path on the plugin's
  own address; no redirect address is ever taken from the request;
- the token works only at that plugin's own `/api/`, never at EpicStaff's API.

A plugin can log people in only when it has a backend: the platform config
(`/.well-known/epicstaff/config.json`) then has `login.authorize_url` and `login.token_url`;
for a plugin without a backend `login` is `null`.

## The flow

```
plugin page (https://weather.plugins.example.com)            EpicStaff (https://epicstaff.example.com)
 1. make code_verifier and state, keep them in sessionStorage
 2. location.replace ──▶ GET /api/auth/plugin-authorize/?plugin=…&state=…&code_challenge=…
                                                     reads the session from EpicStaff's cookie
                                                     ◀── 302 to the plugin's callback page,
                                                         #code=…&state=…  (or #error=…&state=…)
 3. callback page checks state, hands the code to the page
 4. fetch POST /api/auth/plugin-token/ {code, code_verifier}   ──▶  checks code, verifier, Origin
                                                     ◀── 200 {access_token, …}
 5. fetch /api/… with Authorization: Bearer <access_token>  ──▶  plugin's gateway ──▶ plugin backend
```

Every navigation in the flow uses `location.replace`, so logging in adds no entries to the
browser's history (inside EpicStaff's frame, an entry would land in EpicStaff's own history).

The **silent** variant (step 2 inside a hidden frame, with `prompt=none`) is how the SDK logs in
without any visible page and renews the token before it expires. The answer then goes to the
silent callback page, which posts it to the plugin page holding the frame (target origin: the
plugin's own origin, never `*`).

## Step 1: authorize

`GET /api/auth/plugin-authorize/` on EpicStaff's origin, as a top-level or frame navigation.

| Parameter | Rule |
|---|---|
| `plugin` | Required. The plugin's identifier. The plugin must be running and have a backend |
| `state` | Required. 43 to 128 base64url characters, fresh for every login (the SDK uses 32 random bytes) |
| `code_challenge` | Required. `base64url(SHA-256(code_verifier))`, 43 characters |
| `code_challenge_method` | Required. `S256` |
| `org` | Optional. The id of the EpicStaff organization to log in to |
| `prompt` | Optional. `none` for a silent request: never show a page, answer at once |

Any other parameter (such as `redirect_uri` or `return_path`), a parameter given twice, or a
value that breaks its rule gets `400 invalid_authorize_request` as JSON, with `errors[]` naming
each parameter. A plugin that is not running or has no backend gets `404 plugin_not_found`.
Neither is a redirect.

Otherwise the answer is a redirect, decided in this order:

1. **The session.** EpicStaff reads its own refresh cookie, as its refresh endpoint does, but
   only reads it: the cookie is neither rotated nor changed. Without a valid session, a silent
   request goes back with `login_required`; any other goes to EpicStaff's login page, which
   continues the same request after the person logs in.
2. **The organization.** The person may use the plugin in an organization when they are an
   active member of it, the organization is active, the plugin is granted to it, and their role
   there has the plugin's `read` action ([user permissions](../how-to/user-permissions.md)).
   Being a SuperAdmin gives nothing here: only memberships count.
   - With `org`, that organization must be one of them, else `access_denied`.
   - Without `org`: none gives `access_denied`; exactly one is used; several send the person to
     EpicStaff's organization chooser, or answer `interaction_required` on a silent request.
   - A person who may use the plugin once an upgrade finishes (the plugin is stopped for its
     upgrade, or their organization's upgrade has not finished) gets `temporarily_unavailable`
     instead of `access_denied`.
3. **The code.** EpicStaff issues a one-time code and redirects to the plugin's callback page.

| Redirect | Target |
|---|---|
| Code | `https://<id>.<plugins base domain>/.well-known/epicstaff/callback.html#code=<code>&state=<state>` |
| Refusal | The same page, `#error=<error>&state=<state>` (see [login callback errors](error-codes.md#login-callback-errors)) |
| Silent request | `…/.well-known/epicstaff/silent-callback.html` instead of `callback.html` |
| Login | `https://<EpicStaff>/plugin-login?continue=<this request, rebuilt>` |
| Chooser | `https://<EpicStaff>/plugin-choose-org?continue=<this request, rebuilt>` |

The callback pages are served by EpicStaff on every plugin's address; a plugin cannot replace
them. The `continue` value is rebuilt from the checked parameters and never contains `prompt`.

A code is 43 base64url characters, lives **60 seconds**, works **once**, and is bound to the
person, the organization, the plugin, the `code_challenge`, the plugin's origin and the
person's current password: a password change before the exchange ends it. Responses of
both steps carry `Cache-Control: no-store` and never set a cookie.

## Step 2: exchange the code

`POST /api/auth/plugin-token/` on EpicStaff's origin, from the plugin's page:

```js
const response = await fetch(config.login.token_url, {
  method: 'POST',
  credentials: 'omit',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ code, code_verifier }),
});
```

- The body must be JSON (`Content-Type: application/json`, else `415 unsupported_media_type`)
  holding exactly `code` and `code_verifier` (43 to 128 characters of `A-Z a-z 0-9 . _ ~ -`),
  else `400 invalid`.
- The code is used up first. It must exist and be unexpired, the request's `Origin` must be the
  plugin's own origin, the verifier must match the challenge, and the person's password must
  not have changed since step 1; otherwise `400 invalid_grant`, and the code is gone even when
  only the verifier was wrong.
- The person's access is checked again: if they lost it since step 1 (or the plugin stopped
  running), `403 plugin_access_denied`.
- The endpoint never reads or sets a cookie: only the code says who logs in.
- It answers CORS for the plugin's own origin only (a preflight allowing `POST` and
  `content-type`), and never allows credentials.
- More than 120 exchanges a minute from one address get `429 throttled`.

```ts
interface PluginTokenResponse {
  access_token: string;
  token_type: 'Bearer';
  expires_in: 900;                                  // seconds
  plugin: { identifier: string; version: string };
  org: { id: number; name: string };
  user: { id: number; email: string; name: string };
  plugin_permissions: string[];                     // manifest order, always includes "read"
}
```

## Using the token

Send it only to the plugin's own `/api/`, as `Authorization: Bearer <access_token>`. The
gateway checks it on every request and forwards the request to the backend with a
[user context](gateway-context.md); the token itself never reaches the backend. Keep it in
memory only, never in `localStorage`, `sessionStorage` or a cookie.

- **Lifetime.** 15 minutes. Renew it silently a minute before it expires (the SDK does).
- **401 `login_required`** from the plugin's `/api/`: the token is no longer acceptable. Renew
  once and retry; if renewal answers `login_required`, the EpicStaff session has ended.
- **403 `forbidden`**: the person may no longer use the plugin in that organization. Do not
  retry.
- **Logging out of EpicStaff** ends renewals at once, but a token already issued keeps working
  until it expires, like EpicStaff's own access tokens.
- The token is for one organization. To work in another, log in again with `org`; inside
  EpicStaff's frame, switching organizations reloads the plugin page.

EpicStaff's own API refuses a plugin login token. See below for what a plugin page may ask of
EpicStaff at all.

## What a plugin page cannot do

A plugin page talks to EpicStaff only through the login above. EpicStaff refuses everything
else before it is handled:

- **No cross-origin calls to EpicStaff's API.** A request whose `Origin` is a plugin address
  (or any host under the plugins base domain) gets `403 plugin_origin_refused` on every path
  except the token
  exchange from the plugin's own origin and the authorize navigation. That includes
  `/api/plugin-public/*`: a page loads its platform config from its own
  `/.well-known/epicstaff/config.json`, never from EpicStaff's address.
- **No hidden origin on the session endpoints.** A request with `Origin: null` (a page using
  `referrerPolicy: 'no-referrer'`, or a sandboxed frame) gets `403 plugin_origin_refused` on
  every `/api/auth/` endpoint and on the password-change confirm, except `GET`, `HEAD` and
  `OPTIONS`. These are
  the endpoints that read or write EpicStaff's refresh cookie.
- **No form or text bodies at login.** EpicStaff's login and first setup take
  `application/json` only (`415 unsupported_media_type` otherwise), so no page can log the
  browser in to an account of its choosing with a form post.

## The organization chooser's list

`GET /api/plugins/{identifier}/login-organizations/` gives EpicStaff's chooser page the
organizations the logged-in caller may open a plugin in. It needs EpicStaff's own login (a
plugin login token is refused) and ignores `X-Organization-Id`.

```json
{ "plugin": { "identifier": "weather", "name": "Weather", "icon_url": "/api/plugin-public/weather/icon/?v=0.3.0" },
  "organizations": [ { "id": 3, "name": "Acme" } ] }
```

The list holds only the caller's own organizations, sorted by name, and is empty for a
SuperAdmin who is a member nowhere. An unknown plugin, one that is not running, or one without
a backend gets `404 plugin_not_found`.

## What a plugin can rely on

- EpicStaff and the plugins share one registrable domain, so the browser sends EpicStaff's
  session cookie (`SameSite=Lax`) with the authorize navigation even inside EpicStaff's frame.
- The JS SDK needs a secure context: HTTPS, or `http://*.localhost` for local development.
- Codes and tokens are never written to EpicStaff's logs.
