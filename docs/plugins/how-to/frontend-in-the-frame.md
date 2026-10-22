# Build a plugin's frontend for EpicStaff's frame

A plugin's page is a single-page app built to static files, in any framework. EpicStaff shows it in a frame on the
plugin's own origin (`<id>.<plugins base domain>`); people can also open that address directly. This page lists what a
page has to do to behave well in both places. The [Weather sample](../../../plugin-samples/weather/spa/) does all of
it in a few hundred lines of plain TypeScript.

## Start the SDK before the router

```ts
const plugin = await startPlugin({ routing: 'pathname' });
const login = createPluginLogin(plugin); // only for a plugin with a backend
startRouter();
await login.start();
```

`startPlugin` removes EpicStaff's `es_org` hint from the address before your router reads it, and from then on keeps
EpicStaff's address in step with your routes ([Frame protocol](../reference/frame-protocol.md#navigation)).

## Use relative paths and the platform config

- Never hard-code your plugin's address or EpicStaff's: the same build runs on every deployment.
- Serve assets with absolute paths (`/app-1a2b.js`), so a deep link such as `/oauth/callback` loads them.
- The platform config at `/.well-known/epicstaff/config.json` tells the page EpicStaff's origin, its own API prefix and
  where to sign in; `startPlugin` loads it.

## History: replace, never push

Inside EpicStaff every navigation of your frame lands in EpicStaff's own history. `startPlugin` turns your router's
`pushState` into `replaceState` plus a message to EpicStaff, which adds the entry to its own address instead. Do not
navigate the frame with links to other documents, `location.assign` or `location.href = …` in a flow the person did
not ask for; use `location.replace` when you must. The SDK's sign-in does.

## Sign in and call your backend

- Show the sign-in states: "Signing in…", "You do not have access to … in this organization" (`access-denied`),
  "Your EpicStaff session has ended" with a "Sign in again" button (`session-ended`, which inside EpicStaff never
  navigates on its own), "… is being updated. It will be back in a few minutes." (`maintenance`), and an error with
  "Try again" (`failed`). See [JS SDK](../reference/js-sdk.md#pluginlogin).
- Call your own API only through `login.fetch('/api/…')`. It adds the person's token, renews it when the gateway asks,
  and never sends it anywhere else.
- Keep the token where the SDK keeps it: in memory. Do not copy it into `localStorage`, `sessionStorage`, cookies or
  URLs.
- `login.session` names the person, the organization and their plugin permissions, for display. Your backend must not
  trust the browser for any of it: it reads the signed [gateway context](../reference/gateway-context.md) instead.
- Public pages of your plugin can render before the sign-in finishes; pages that need the person can wait for
  `login.state === 'signed-in'` (`onChange` tells you).

The person's token works only on your plugin's `/api/` through EpicStaff's gateway. A plugin page cannot use
EpicStaff's own API: EpicStaff refuses every request from a plugin origin except the token exchange.

## While your plugin is being updated

During an upgrade the gateway answers your `/api/` with `503` and `X-EpicStaff-Gateway-Deny: maintenance`: while the
plugin itself is offline, and, once it is back, for the people of each organization until that organization's upgrade
hook has finished. EpicStaff also signs nobody in to the plugin in such an organization, so `login.state` can be
`maintenance` too.

- **Inside EpicStaff** there is nothing to build. `login.fetch` tells EpicStaff (`availability.changed`), and EpicStaff
  shows its own maintenance panel instead of your page, then opens your page again once the plugin is back.
- **On your own address**, show "… is being updated. It will be back in a few minutes." while `login.availability` is
  `maintenance`, and check again every 30 seconds: `renew()` when `login.state` is `maintenance`, then any route behind
  the sign-in through `login.fetch`. Ask such a route, not a public path, which answers as soon as the plugin runs. See
  [Availability](../reference/js-sdk.md#availability).
- Pages already loaded keep their state, so reload what they show once `availability` is `available` again: an answer
  that came during the update was a refusal.

The [Weather sample](../../../plugin-samples/weather/spa/src/availability.ts) does exactly this.

## Streaming and WebSockets

A browser cannot set `Authorization` on a WebSocket, so a WebSocket to your `/api/` cannot carry the person's token in
this version. Until it can:

- stream with Server-Sent Events or a streamed `fetch` response through `login.fetch` (the gateway does not buffer
  `/api/` responses), or
- issue your own short-lived, single-use ticket from an authenticated `POST /api/ws-ticket`, and accept the WebSocket
  on a declared [public path](public-paths.md) that checks the ticket. The public path's context has no person: your
  backend links the ticket to the person when it issues it.

## Theme

Take every colour from the `--es-*` tokens, with defaults in `:root` for the page outside EpicStaff
([Frame protocol](../reference/frame-protocol.md#theme)). The SDK applies EpicStaff's values and follows theme changes.

## Popups for external providers

A provider's sign-in page cannot be framed; open it in a popup with `login.openPopup`, from a click handler. See
[Receive an external provider's callback](external-callbacks.md).

## Check it

- Inside EpicStaff: open the plugin from the left bar, move between your routes, use EpicStaff's Back and Forward, and
  switch organization (the frame reloads in the new organization).
- On its own: open `https://<id>.<plugins base domain>/<route>` in a new tab; EpicStaff's login or organization chooser
  appears and brings you back to the same route.
- [Local development](local-development.md) shows how to run all of this on your machine.
