# Frame protocol 1

How a plugin's page and the EpicStaff page that frames it talk to each other: the frame address, the handshake, the
messages, navigation sync and theme tokens.

The protocol is **optional**. A plugin page that never speaks it still opens inside EpicStaff; it only misses address
sync and theme tokens. The JS SDK (`@epicstaff/plugin-sdk`, in `plugin-sdk/`) implements the plugin side, so most
plugins call one function and never handle these messages themselves.

The machine-readable source of every constant on this page is
[`plugin-sdk/contracts/frame-protocol.json`](../../../plugin-sdk/contracts/frame-protocol.json). The SDK tests and an
EpicStaff frontend test both assert their constants equal it.

## The frame

A person opens a plugin from the left bar of EpicStaff. EpicStaff's address `/plugins/<id>/<rest>?<query>` shows the
plugin page `/<rest>?<query>` in a frame:

```html
<iframe
    src="<frame origin>/<rest>?<query>&es_org=<organization id>"
    sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals"
    referrerpolicy="strict-origin"
    allow="clipboard-write"
></iframe>
```

| Part | Value |
|---|---|
| Frame origin | `https://<id>.<plugins base domain>[:<port>]` — every plugin has its own origin. Plain `http` only on `*.localhost` hosts, for local development |
| `es_org` | The organization the person opened the plugin in, appended with `?` or `&` after the page's own query. EpicStaff removes an `es_org` of the page's own first: the name is reserved |
| Sandbox | The page keeps its real origin (`allow-same-origin`). There is no `allow-top-navigation`: a plugin page cannot navigate EpicStaff away |
| Credentials | None. The frame address and the messages never carry a token, a cookie or any other secret |

The plugin host only accepts being framed by EpicStaff (`Content-Security-Policy: frame-ancestors 'self'
<EpicStaff origin>`).

### Platform config

Every plugin host serves `/.well-known/epicstaff/config.json` on the plugin's own origin:

```json
{
    "plugin": { "identifier": "weather", "name": "Weather", "version": "0.1.0" },
    "epicstaff_origin": "https://epicstaff.example.com",
    "frame_protocol": 1,
    "api_base": "/api/",
    "login": null
}
```

`epicstaff_origin` is the only origin the page may talk to over this protocol. `login` stays `null` until EpicStaff
offers sign-in to plugin pages.

## Handshake

```
plugin page                                         EpicStaff
    │  es:ready ──── window.parent.postMessage(…, epicstaff_origin) ──▶  │
    │                                                                    │ checks source and origin
    │  ◀── es:init + MessagePort ── frame.contentWindow.postMessage(…, frame origin, [port])
    │                                                                    │
    │  ◀═════════ every later message travels on the port ═════════▶     │
```

1. The page loads the platform config, then posts `{"type":"es:ready","protocol":1}` to `window.parent` with
   `epicstaff_origin` as the target origin.
2. EpicStaff accepts `es:ready` only when `event.source` is the frame's window **and** `event.origin` is the frame
   origin. It answers `es:init` to that exact origin and transfers one `MessagePort`.
3. When `es:ready` carries another `protocol`, EpicStaff answers `es:error` (no port) instead.
4. The page accepts `es:init` and `es:error` only when `event.source` is `window.parent` **and** `event.origin` is
   `epicstaff_origin`. Without `es:init` within **3 seconds** it runs unframed.
5. A later `es:ready` from the same frame means the page reloaded: EpicStaff closes the old port and answers a new
   `es:init` with the address it shows now.

## Messages

Every message is a JSON object with a `type`. Both sides ignore a `type` they do not know, so later versions can add
messages without breaking older pages.

| Direction | Channel | Message |
|---|---|---|
| page → EpicStaff | `window.parent.postMessage` | `{"type":"es:ready","protocol":1}` |
| EpicStaff → page | `postMessage` with the port | `{"type":"es:init","protocol":1,"theme":{"mode":"dark","tokens":{"--es-color-background":"#1e1f22"}},"nav":{"path":"/forecast?city=Berlin"},"org":{"id":3,"name":"Acme"}}` |
| EpicStaff → page | `postMessage`, no port | `{"type":"es:error","protocol":1,"code":"unsupported_protocol"}` |
| page → EpicStaff | port | `{"type":"nav.changed","path":"/forecast?city=Paris","replace":false}` |
| EpicStaff → page | port | `{"type":"nav.navigate","path":"/about"}` |
| EpicStaff → page | port | `{"type":"theme.changed","theme":{"mode":"light","tokens":{"…":"…"}}}` |

| Field | Meaning |
|---|---|
| `nav.path` in `es:init` | The page's path EpicStaff's address shows. When the page started somewhere else (the address moved while the frame loaded), it should move there |
| `org` | The organization the page was opened in. It is a display hint, not proof of anything: a plugin backend checks the organization itself |
| `replace` | `true`: replace EpicStaff's history entry; `false`: add one |
| `code` | Only `unsupported_protocol` in protocol 1 |

## Navigation

EpicStaff's history is the only history. A navigation inside a cross-origin frame still adds an entry to the browser's
session history, so a page in the frame must not push its own entries; it reports them instead.

- **The page navigates:** it changes its own address with `history.replaceState` and sends `nav.changed` with
  `replace: false` for what would have been a push, `replace: true` for a replace. EpicStaff moves its address (adding
  or replacing an entry); the frame is not reloaded.
- **EpicStaff navigates** (Back, Forward, a link to `/plugins/<id>/…`): EpicStaff sends `nav.navigate`; the page moves
  to that path without reporting it back.
- **Both at once:** a navigation the person starts in EpicStaff wins over a `nav.changed` that arrives meanwhile.
- **Routing modes:** the page may keep its route in the address path (`/forecast`, the default) or in the hash
  (`#/forecast`). Either way the protocol carries the same path form.

### Path grammar

```
^/([A-Za-z0-9\-._~%]+(/[A-Za-z0-9\-._~%]+)*)?(\?[A-Za-z0-9\-._~%=&+]*)?$
```

A path is absolute, has no empty segment, no fragment and no `.` or `..` segment (also not when `%`-encoded), every
`%` escape decodes as UTF-8, and it is at most **1024** characters. In the query `+` means a space. EpicStaff drops a
path that breaks these rules. Both sides compare paths in one canonical spelling (every character outside
`A-Z a-z 0-9 - . _ ~` written as an uppercase `%XX` escape), so a router that spells the same address differently is
not an echo. `canonical_vectors` in the contract file lists paths with their canonical spelling (`null` for a path that
is refused); the SDK and EpicStaff are both tested against it.

### Rate limit

EpicStaff accepts at most **120** `nav.changed` messages per frame in any 60 seconds and drops the rest. Reloading the
page does not reset the count. The SDK stays below the limit and sends the latest path once the window allows.

### Organization switch

When the person switches organization, EpicStaff rebuilds the plugin page for the new organization: the frame reloads
at the plugin's root with the new `es_org`. A page never sees the organization change under it.

## Theme

`es:init` carries the theme, and `theme.changed` follows every change. `mode` is `dark` unless EpicStaff runs its light
theme. `tokens` holds these CSS custom properties; a token EpicStaff does not define is left out.

| Token | Use |
|---|---|
| `--es-color-background` | Page background |
| `--es-color-surface` | Cards and panels |
| `--es-color-surface-raised` | Dialogs and menus |
| `--es-color-sidenav` | EpicStaff's left bar |
| `--es-color-text` | Main text |
| `--es-color-text-secondary` | Secondary text |
| `--es-color-text-tertiary` | Least important text |
| `--es-color-text-disabled` | Disabled text |
| `--es-color-accent` | Primary actions, selection |
| `--es-color-accent-hover` | Primary actions on hover |
| `--es-color-accent-active` | Primary actions while pressed |
| `--es-color-input-background` | Form fields |
| `--es-color-input-border` | Form field borders |
| `--es-color-input-placeholder` | Placeholder text |
| `--es-color-border` | Borders |
| `--es-color-divider` | Dividers |
| `--es-color-divider-subtle` | Hairline dividers |
| `--es-color-success` | Success |
| `--es-color-warning` | Warnings |
| `--es-color-error` | Errors |
| `--es-focus-ring` | Focus ring (a `box-shadow` value) |
| `--es-font-family` | Font stack |

The set only grows: EpicStaff adds tokens but never renames or removes one. Give every token a default for the page
running outside EpicStaff, for example in `:root`; the SDK sets the tokens on `<html>`, which wins over those defaults.

## Using the JS SDK

```ts
import { startPlugin } from '@epicstaff/plugin-sdk';

// Before the router starts: removes es_org from the address and captures the first navigation.
const plugin = await startPlugin({ routing: 'pathname' });

plugin.framed; // true inside EpicStaff
plugin.org; // { id, name } from es:init, or null
plugin.orgHint; // the es_org value, kept even unframed
plugin.onThemeChange((theme) => console.log(theme.mode));
```

`startPlugin` loads the platform config, runs the handshake, applies the theme to `<html>` (the tokens,
`data-es-theme="dark|light"` and `color-scheme`), turns `history.pushState` into `replaceState` plus `nav.changed`, and
answers `nav.navigate` by replacing the address and firing `popstate` (and `hashchange` in hash mode), which most
routers follow. Pass `onNavigate` to call your router directly, and `applyTheme: false` to apply the theme yourself.

The [Weather sample](../../../plugin-samples/weather/) is a complete page built this way: two routes, colours only from
the tokens, no network calls besides the platform config.

## Without the SDK

A page that wants only the theme can run the handshake itself:

```js
const config = await (await fetch('/.well-known/epicstaff/config.json')).json();
addEventListener('message', function onInit(event) {
    if (event.source !== window.parent || event.origin !== config.epicstaff_origin) return;
    if (event.data?.type !== 'es:init') return;
    removeEventListener('message', onInit);
    for (const [name, value] of Object.entries(event.data.theme.tokens)) {
        document.documentElement.style.setProperty(name, value);
    }
    const port = event.ports[0];
    port.onmessage = (message) => {
        // nav.navigate and theme.changed arrive here.
    };
});
window.parent.postMessage({ type: 'es:ready', protocol: 1 }, config.epicstaff_origin);
```

Always check both `event.source` and `event.origin`, and never send anything secret over the protocol.

## Compatibility

| Change | Allowed within protocol 1 |
|---|---|
| A new message type | Yes; the other side ignores it |
| A new theme token | Yes |
| A new field in an existing message | Yes; ignore fields you do not know |
| Renaming or removing a message, field or token | No; that is a new protocol version |
