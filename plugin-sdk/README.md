# @epicstaff/plugin-sdk

Everything an author needs to build a **plugin app** — a real, multi-screen frontend that EpicStaff shows inside its
own shell and that works with EpicStaff data through the plugin bridge (version 2):

- **Bridge client** — `connect()`: handshake, typed calls, events, `flows.runAndWait`, key-value reads, address-bar
  sync, theme tokens.
- **Storage stand-in** — `@epicstaff/plugin-sdk/storage-shim`: in-memory `localStorage`, `sessionStorage` and
  `document.cookie`, because the sandbox throws on all three.
- **Mock host** — `@epicstaff/plugin-sdk/mock-host`: speaks the same protocol from local sample data, so the app runs
  in a normal browser tab (`npm start`) with no EpicStaff at all.
- **CLI** — `epicstaff-plugin validate` and `epicstaff-plugin pack`: checks a plugin against the package rules and
  writes the zip.

The SDK lives in the EpicStaff repository and is not published to npm. A complete example is the Chat Admin sample:
`plugin-samples/chat-admin/` ([README](../plugin-samples/chat-admin/README.md)).

## Quick start

```jsonc
// package.json of your app (path relative to the app folder)
"dependencies": { "@epicstaff/plugin-sdk": "file:../path/to/EpicStaff/plugin-sdk" }
```

Build the SDK once (`npm --prefix plugin-sdk install && npm --prefix plugin-sdk run build`), or compile it with your
app's TypeScript: `tsc -p <path>/plugin-sdk/tsconfig.json` (the sample's `build:sdk` script does this).

```ts
// main.ts — the very first import
import '@epicstaff/plugin-sdk/storage-shim';
```

```ts
import { connect } from '@epicstaff/plugin-sdk';

// Call once, before your router's first navigation (Angular: inside provideAppInitializer).
const bridge = await connect({
    // Used only when the page is not inside EpicStaff; a lazy import keeps it out of production bundles.
    mock: () => import('./mock-data').then((module) => module.createMyMockHost()),
});

const { items, count } = await bridge.kv.list({ table: 'conversations', search: 'c_', ordering: '-updated_at' });
const entry = await bridge.kv.get('conversations', items[0].key);
const output = await bridge.flows.runAndWait<{ answer: string }>('chat', { question: 'Hello?' });
```

The aliases (`conversations`, `chat`) are the `access[].alias` values of your `plugin.json`. A page never sees a
database id.

## How a plugin app runs

EpicStaff serves the files of `ui/` from `/api/plugin-ui/<token>/…` into `<iframe sandbox="allow-scripts">`. The page
has an **opaque origin** (`null`) and this content security policy:

```
sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; media-src 'none'; frame-src 'none';
worker-src 'none'; manifest-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'
```

Every file is sent with `Access-Control-Allow-Origin: *`, so ES modules, lazy chunks and web fonts (all fetched in CORS
mode from the opaque origin) load. The page reaches EpicStaff only through the bridge; the host checks every call
against the plugin's access list and then calls the API **as the signed-in user** (user permissions ∩ access list).

### Sandbox rules

| Works | Does not work |
|---|---|
| ES modules (`<script type="module">`), lazy-loaded chunks (`import()`), `modulepreload` | Inline `<script>` code, `eval`, `new Function`, `javascript:` URLs, inline event handlers (`onclick="…"`) |
| Web fonts bundled with the app (`@fontsource/*`, your own `.woff2`) | Any outside network: `fetch`, XHR, WebSocket, CDNs, Google Fonts, external images — ship everything in the zip |
| Framework-injected styles (`<style>` elements, `style="…"`, CSS-in-JS) | `<base href>` (ignored: `base-uri 'none'`) — relative URLs already resolve inside the plugin's folder |
| Hash routing (`#/path`) with `pushState` / `replaceState` | Path routing (`/conversations`) — the page may only change its URL's query and fragment |
| Images and icons from `ui/`, `data:` and `blob:` URLs | Persistent storage: `localStorage`, `sessionStorage`, cookies, IndexedDB (use the storage stand-in; state lives in memory and in the URL) |
| `click` / `keydown` handlers on buttons and inputs | Form submission — a `<form>`'s `submit` event never fires without `allow-forms` (Angular's `(ngSubmit)` stays silent). Handle the button's `click` and Enter in a `keydown` handler |
| Talking to EpicStaff through the bridge | `alert` / `confirm` / `prompt`, popups, new windows, downloads, nested frames, workers, camera / microphone / location |

Limits of a plugin: `ui/` ≤ **300 files** and ≤ **20 MB**; the zip ≤ **30 MB**, ≤ **400 entries**, ≤ **60 MB**
unpacked; icon ≤ 64 KB. UI file types: `.html .js .mjs .css .json .map .txt .svg .png .jpg .jpeg .gif .webp .ico .woff
.woff2 .ttf .otf`. The page link stays valid for 12 hours; after that a not-yet-loaded lazy chunk fails, and reloading
the page fixes it.

## API reference

### `connect(options?) → Promise<EpicStaffBridge>`

Installs nav sync (so it must run before the router's first navigation), posts `{v: 2, kind: "ready"}` to
`window.parent`, waits for `init` and the `MessagePort`, applies the theme. Outside a frame (`window.parent === window`)
it connects to the mock host instead. One bridge per page: every later call returns the same promise. On a page
reload (including a dev-server live reload) the new page posts `ready` again and EpicStaff re-handshakes.

| Option | Default | Meaning |
|---|---|---|
| `timeoutMs` | `10000` | How long to wait for EpicStaff to answer the handshake (`BridgeCallError` `timeout`) |
| `requestTimeoutMs` | `30000` | Default timeout of every call |
| `mock` | an empty `createMockHost()` | `MockHost`, or a factory `() => MockHost \| Promise<MockHost>`, used when not framed. `false`: fail instead. The default is loaded with a dynamic `import()`, so it is a lazy chunk in your build that an app inside EpicStaff never downloads |
| `forceMock` | `false` | Use the mock even inside a frame |
| `navSync` | `true` | Keep EpicStaff's address bar in sync. `{ onNavigate(path) }` handles `nav.navigate` yourself; `false` turns it off |
| `theme` | `true` | Apply EpicStaff's theme to `<html>` and follow `theme.changed` |
| `window` | global `window` | For tests |

The handshake rejects with `BridgeCallError` (`timeout`, or EpicStaff's code — e.g. `unsupported` when `plugin.json`
declares another bridge version).

### `EpicStaffBridge`

| Member | Does |
|---|---|
| `context` | `init.context`: `plugin {id, version, name}`, `access [{alias, type, actions}]`, `nav {path}`, `theme {mode, tokens}` |
| `mocked` | `true` when the mock host answers |
| `call(method, params?, {timeoutMs?, signal?})` | Any v2 method, fully typed (see the table below) |
| `on(topic, (data, subscription) => …)` | Subscribes to an event topic; returns the unsubscribe function |
| `flows.run(flow, variables?)` | `flows.run` → `{session_id}` |
| `flows.runAndWait(flow, variables?, options?)` | Runs, subscribes, resolves with the End node's output (`end_node_result`) |
| `sessions.get / subscribe / unsubscribe / stop` | The v1 session methods (only sessions this page started) |
| `kv.list({table, search?, ordering?, limit?, offset?})` | `{count, items: [{key, value_preview, value_truncated, created_at, updated_at}]}` |
| `kv.get(table, key)` | `{key, value, created_at, updated_at}`; `not_found` when there is no such key |
| `nav.path` | The current app path in canonical form, e.g. `/conversations?page=2` |
| `nav.report(path, replace?)` | Reports a path yourself (only needed with `navSync: false`) |
| `nav.onNavigate(handler)` | Called after each `nav.navigate` from EpicStaff |
| `theme.current`, `theme.onChange(handler)` | The theme and its changes (the SDK already applies them to `<html>`) |
| `close()` | Rejects waiting calls with `closed`, closes the port, restores `history` |

`flows.runAndWait` options: `timeoutMs` (default 300 000), `signal` (`AbortSignal`), `onSession(sessionId)`,
`onMessage(message)` (every `session.message`, for progress), `onStatus(status)`. It rejects with a `FlowRunError` whose
`reason` is `failed` (status `error` / `stop` / `expired`), `no_output` (ended without an End node result),
`disconnected`, `timeout` or `aborted`; a failing bridge call (e.g. `forbidden`) rejects with its `BridgeCallError`,
and `close()` rejects a waiting run at once with `BridgeCallError` `closed`. Giving up never stops the session in
EpicStaff; call `bridge.sessions.stop(id)` (from `onSession`) for that. The callbacks never change the outcome: it is
decided first, and a callback that throws is reported with `reportError` (the same holds for `on`, `nav.onNavigate`
and `theme.onChange` handlers).

### Methods (bridge v2)

| Method | Params | Needs | Result |
|---|---|---|---|
| `bridge.hello` | — | — | `{bridge_version, plugin, access, methods}` |
| `flows.run` | `{flow, variables?}` | `run` on a flow alias | `{session_id}` |
| `sessions.get` | `{session_id}` | `sessions.read` | `{status, variables, flow}` |
| `sessions.subscribe` | `{session_id}` | `sessions.read` | `{subscription}`, then `session.message` / `session.status` / `subscription.closed` |
| `sessions.unsubscribe` | `{subscription}` | — | `{}` |
| `sessions.stop` | `{session_id}` | `sessions.stop` | `{}` |
| `kv.list` | `{table, search? (≤512), ordering? ("key" \| "-key" \| "updated_at" \| "-updated_at", default "key"), limit? (1–100, default 20), offset? (≥0)}` | `read` on a key-value table alias | `{count, items}` |
| `kv.get` | `{table, key}` — key `^[A-Za-z_][A-Za-z0-9_]*$`, ≤512 | `read` | `{key, value, created_at, updated_at}` |
| `nav.changed` | `{path, replace?}` | — | `{}` |

Host events (`subscription: null`): `nav.navigate {path}` (EpicStaff's address changed: Back/Forward, sidenav click,
address bar) and `theme.changed {mode, tokens}`.

### Errors

`BridgeCallError` has `code` and `method`. Codes from EpicStaff: `bad_request`, `forbidden`, `not_found`,
`rate_limited`, `unsupported`, `internal`. Codes the client raises: `timeout`, `closed`, `aborted`. Branch on `code`,
never on `message`.

Limits per open page: request ≤ 64 KB (the client refuses bigger ones with `bad_request` before sending), ≤ 10 requests
in flight (the client queues the rest instead of failing; a call that timed out or was aborted keeps its slot until
EpicStaff answers it, because EpicStaff counts it until then — at most 2 minutes), ≤ 4 subscriptions, ≤ 20 `flows.run` per minute, ≤ 120
`nav.changed` per minute (nav sync holds reports back to stay under it). Because of the 64 KB cap, send ids, not data:
the Chat Admin flow reads the transcript from its own table, and the app sends only `{conversation_id, question}`.

### Navigation (address-bar sync)

EpicStaff owns the browser history; the app owns its screens. The app's route lives in the iframe URL's fragment, and
EpicStaff shows it under its own address: `/plugins/<id>/conversations/c_…?page=2`. Deep links survive a refresh,
Back/Forward step through app screens one at a time.

- At start EpicStaff opens the frame at `…/index.html#<path>` and sends the same `path` in `init`. If EpicStaff's
  address changed in between, the SDK moves the app to `init`'s path without reporting it back.
- The SDK patches `history.pushState` to **replace** the frame's entry and report `nav.changed {path, replace: false}`
  (a push inside the frame would add a second entry to the browser history); `history.replaceState` reports
  `{replace: true}`. Changes made before the handshake are queued; the latest wins.
- On `nav.navigate` the SDK sets the hash with `replaceState` and dispatches synthetic `popstate` and `hashchange`, which
  routers (Angular, React Router, Vue Router) follow. Pass `navSync: { onNavigate }` to route yourself instead.
- Paths are compared in one canonical spelling (the one EpicStaff uses: every character outside `A-Z a-z 0-9 - . _ ~`
  as uppercase `%XX`, `+` in the query as `%20`), so a router re-spelling the same URL never echoes back.
  `canonicalNavPath()` and `hashToNavPath()` are exported.

Use a **hash router built on `pushState`** (Angular `withHashLocation()`, React Router `createHashRouter`, Vue Router
`createWebHashHistory`). Code that assigns `location.hash` directly or uses plain `<a href="#/x">` links adds frame
entries to the browser history (Back then needs two steps); the SDK still keeps the address bar right.

### Theme

`init` and `theme.changed` carry `mode` (`dark` | `light`) and tokens. The SDK sets every token on `<html>`, plus
`data-es-theme="dark|light"` and `color-scheme`. Using them is optional; always give a fallback, so the app also looks
right standalone: `color: var(--es-color-text, #d9d9de)`. EpicStaff only adds tokens, never renames them:

| Token | EpicStaff variable | Dark value |
|---|---|---|
| `--es-color-background` | `--color-background-body` | `#212325` |
| `--es-color-surface` | `--color-surface-card` | `#232323` |
| `--es-color-surface-raised` | `--color-modals-background` | `#222225` |
| `--es-color-sidenav` | `--color-sidenav-background` | `#222225` |
| `--es-color-text`, `-secondary`, `-tertiary`, `-disabled` | `--color-text-*` | `#d9d9de`, 60 %, 40 %, `#676767` |
| `--es-color-accent`, `-hover`, `-active` | `--accent-color*` | `#685fff`, `#574fd6`, `#473fb3` |
| `--es-color-input-background`, `-border`, `-placeholder` | `--color-input-*` | `#27272b`, `#c8ceda24`, `#c8ceda4d` |
| `--es-color-border`, `--es-color-divider`, `--es-color-divider-subtle` | `--color-border`, `--color-divider-*` | `#c8ceda24`, `#c8ceda24`, `#c8ceda14` |
| `--es-color-success`, `-warning`, `-error` | status colours | `#2aba6b`, `#f5a623`, `#f54242` |
| `--es-focus-ring` | `--focus-ring` | `0 0 0 2px rgba(104, 95, 255, 0.4)` |
| `--es-font-family` | `--font-family` | `Inter, 'Helvetica Neue', sans-serif` |

`MOCK_DARK_THEME` and `MOCK_LIGHT_THEME` (from `@epicstaff/plugin-sdk/mock-host`) hold the full sets.

### Storage stand-in

`import '@epicstaff/plugin-sdk/storage-shim'` replaces `localStorage`, `sessionStorage` and `document.cookie` with
in-memory versions wherever the browser throws on access; where they work it leaves them alone. Call
`installStorageShim({ force: true })` to replace them everywhere (no persistence even standalone). Nothing survives a
reload. Bundlers may evaluate chunks shared with lazy routes before the entry's own code; if a library touches storage
while its module loads, also list the shim as a separate entry that runs first (Angular: `"polyfills":
["@epicstaff/plugin-sdk/storage-shim"]`).

### Mock host

```ts
import { createMockHost } from '@epicstaff/plugin-sdk/mock-host';

export const createMyMockHost = () =>
    createMockHost({
        plugin: { id: 'chat-admin', version: '0.1.0', name: 'Chat Admin' },
        flows: {
            // (variables, {sessionId, kv}) => End node output; may be async; throwing fails the run
            chat: async ({ question }, { kv }) => ({ answer: `You asked: ${question}` }),
        },
        kvTables: { conversations: [{ key: 'c_1', value: { title: 'Hello', turns: 1 } }] },
    });
```

Options: `plugin`, `access` (default: every flow with all flow actions, every table with `read`), `flows`, `kvTables`,
`theme` (default dark), `initialPath` (default: the page's own path), `latencyMs` (120), `closeGraceMs` (300),
`onNavChanged`. The mock validates like EpicStaff (unknown method → `unsupported`, unknown param or bad value →
`bad_request`, wrong alias / type / action → `forbidden`, other sessions → `not_found`, the same limits), previews values
like Postgres `jsonb`, and replays session history on subscribe. `host.kv` reads and writes its tables (a mocked flow
gets it as `context.kv`); `host.navigate(path)` and `host.setTheme(theme)` push host events; `host.navChanges` lists
every accepted `nav.changed`.

Import it only from a module that is loaded lazily (e.g. the `mock` factory above): a static import from the main
bundle ships the mock and its sample data to production.

## Building with Angular

```ts
// app.config.ts
provideZonelessChangeDetection(),
provideRouter(routes, withHashLocation(), withComponentInputBinding()),
provideAppInitializer(() => inject(PluginBridgeService).connect()), // a service that calls connect()
```

`angular.json`:

```jsonc
"build": { "options": {
    "polyfills": ["@epicstaff/plugin-sdk/storage-shim"],   // optional; see "Storage stand-in"
    // no "baseHref"
  },
  "configurations": { "production": {
    "outputHashing": "all",
    "optimization": { "scripts": true, "styles": { "minify": true, "inlineCritical": false }, "fonts": false },
    "sourceMap": false
  } } },
"serve": { "options": { "port": 4300, "headers": { "Access-Control-Allow-Origin": "*" } } }
```

- **`inlineCritical: false`** — critical-CSS inlining loads the stylesheet with an inline `onload` handler, which the
  CSP blocks: the app would render unstyled.
- **`fonts: false`** — font inlining downloads Google Fonts at build time; bundle fonts with `@fontsource/*` instead.
- **No base href** — delete `<base href="/">` from `src/index.html` (`ng new` adds it). Hash routing needs no base,
  and all generated URLs are relative.
- **Dev server headers** — the frame's opaque origin loads module scripts and fonts in CORS mode; without
  `Access-Control-Allow-Origin: *` nothing loads in dev mode. `ng serve` sends the header on every response (scripts,
  chunks, prebundled dependencies, `@vite/client`, CSS, fonts), and its live-reload WebSocket accepts `Origin: null`.
- Upload `dist/<app>/browser/` as `ui/`. `3rdpartylicenses.txt` is written next to it, not inside.
- Angular CLI 22 needs Node ≥ 24.15 (or ≥ 22.22.3). On an older Node the CLI stops at its version check; the same
  builder runs with `node node_modules/@angular/cli/bin/bootstrap.js build` (local workaround only — Docker and CI use a
  newer Node).

## Building with Vite (React, Vue, Svelte, …)

```ts
// vite.config.ts
export default defineConfig({
    base: './',                    // relative asset URLs: the app lives under /api/plugin-ui/<token>/
    server: { port: 4300, cors: true, headers: { 'Access-Control-Allow-Origin': '*' } },
    build: { assetsInlineLimit: 4096 }, // data: URLs are allowed
});
```

- Use a hash router: React Router `createHashRouter`, Vue Router `createWebHashHistory`, TanStack Router
  `createHashHistory`.
- Do not use `@vitejs/plugin-legacy` (it injects inline scripts) or CSS `@import` from a CDN.
- `import '@epicstaff/plugin-sdk/storage-shim'` first in `main.tsx`, and `await connect()` before rendering the router.

## Dev mode

Run the app from your dev server inside a real EpicStaff, with real data and the real bridge, and hot reload:

1. EpicStaff must run with `PLUGINS_DEV_MODE=true` (local stacks only; production never has the switch). Install the
   plugin once from its zip.
2. Start your dev server on `localhost` with `Access-Control-Allow-Origin: *` (`npm start` in the sample serves on
   `http://localhost:4300/`).
3. As an admin with `plugins: update`, open **Plugins**, use the plugin's **Dev mode** control and enter
   `http://localhost:4300/` (only `http://localhost` / `127.0.0.1` URLs are accepted).
4. Open the plugin from the left bar: a **DEV** banner shows the URL; the app loads from your dev server. Only you see
   the dev URL — everyone else keeps the installed app. Clear the URL to go back.

Each reload posts `ready` again and EpicStaff re-handshakes; nothing else is needed. Chrome may ask for (or block)
local-network access when EpicStaff itself is not served from `localhost`; dev mode is meant for a local stack.

## CLI

```
epicstaff-plugin validate <plugin-dir> [--ui <ui-build-dir>]
epicstaff-plugin pack <plugin-dir> [--ui <ui-build-dir>] --out <plugin.zip>
```

`<plugin-dir>` holds `plugin.json`, `resources.json` and optionally `knowledge/`, `files/`, `ui/`; `--ui` adds a build
output (e.g. `dist/<app>/browser`) under `ui/` (a path present in both is an error). Run it with
`node <path>/plugin-sdk/bin/epicstaff-plugin.mjs` or, as a dependency, `npx epicstaff-plugin`. No dependencies beyond
Node.

`validate` reports every problem at once (`error` / `warning`, location, message) and exits **1** on any error, **2**
on wrong usage, **0** otherwise. It mirrors EpicStaff's rules — the server stays authoritative:

- layout (only `plugin.json`, `resources.json`, `knowledge/`, `files/`, `ui/`), blocked executable / archive types,
  entry count and unpacked size;
- `plugin.json`: unknown fields refused (a secret slot with a `value` too), versions (`bridge` 1 or 2), id / version /
  alias / slot formats, secret bindings, knowledge, storage files, access entries — `flow` → `run`, `sessions.read`,
  `sessions.stop`; `key_value_table` → `read` and needs `bridge: 2`; duplicates;
- refs: every `ref` names an entity of the right type in `resources.json`;
- `resources.json`: a Flow export with an import format `version` EpicStaff reads (an integer 1–3; absent means 1),
  allowed entity types only, every key-value node uses a table the plugin ships (`KeyValueTable`), table names not
  blank, unique regardless of case and ≤ 255 characters once prefixed (`<plugin_id>__<name>`), no knowledge node bound
  to a collection, no `get_secret("NAME")` in Python code;
- `ui/`: allowed types, ≤ 300 files, ≤ 20 MB, `ui.entry` exists, the icon is a real PNG / SVG ≤ 64 KB;
- every `.html` in `ui/`: inline `<script>` code, `on*=` handlers and `javascript:` URLs are errors; `<base>` and files
  loaded from outside the plugin are warnings.

`pack` validates first and writes nothing on an error. The zip holds the contents of `<plugin-dir>` at its root plus
the UI build under `ui/`, sorted by path, without directory entries, with a fixed timestamp (the same input gives the
same bytes), deflated (or stored when deflating does not help). It refuses an output inside the folders it packs
(symlinks resolved), an `--out` that is a folder, a member name with a `..` segment or a backslash, and a zip over
30 MB.

## Developing the SDK

```
npm --prefix plugin-sdk install
npm --prefix plugin-sdk run build      # tsc → dist/ (ESM + .d.ts)
npm --prefix plugin-sdk test           # build, type-check (src, tests, CLI), node --test
```

Tests run with Node's built-in runner on the built `dist/`, with a fake window (Node has no DOM) and the mock host as
the other end of the protocol. The pack test reads the zip with Python's `zipfile`, the reader EpicStaff uses (skipped
without `python3`). Contracts: bridge v2 in `docs/proto/plugins/plugin-apps-plan.md` §1.5, the package format in §1.1
and §1.4.
