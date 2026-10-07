---
id: plugin-bridge-v2
title: Plugin bridge v2
type: protocol
status: draft
tags: [plugins, prototype, protocol, security, plugin-apps]
created: 2026-10-07
updated: 2026-10-07
related: [plugin-bridge-v1, plugins-rules, plugins-architecture, plugin-package-format, plugin-author-tooling, plugins-api-contract, plugins-glossary, plugins-code-map]
---

# Plugin bridge v2

The bridge for **plugin apps**: everything in [[plugin-bridge-v1]] plus reading the plugin's own key-value tables,
deep links that keep EpicStaff's URL and the app's screen in sync, and EpicStaff's theme pushed live. A plugin chooses
v2 with `"bridge": 2` in its manifest ([[plugin-package-format]]). v1 is untouched: a v1 page keeps its exact old
behaviour ([[plugins-rules]] U3).

Code: `frontend/src/app/features/plugins/bridge/` — `v2/bridge-v2.methods.ts` (method table),
`bridge-protocol.ts` (`BRIDGE_V2_LIMITS`, v2 event topics, init context), `plugin-nav-path.util.ts` (path grammar),
`plugin-bridge-host.service.ts` (host events, dev re-handshake), `../services/plugin-host-theme.service.ts` (tokens).
Page side: `plugin-sdk/src/` ([[plugin-author-tooling]]). Pinned by `v2/bridge-v2.contract.spec.ts`.

## What v2 keeps from v1

The handshake, the envelope (`request` / `response` / `event`), the error codes, the access policy (aliases only,
user ∩ access list, page-scoped sessions), the v1 limits and the teardown rules all apply unchanged with `v: 2`.
v2's `flows.run` and `sessions.*` **are** v1's handlers.

## Handshake changes

1. The host sets the iframe `src` to the page URL **plus a fragment** carrying the app's starting path:
   `…/index.html#/conversations/c_8bfab8dd…`. A hash router can render the right screen before the handshake.
2. The page posts `{v: 2, kind: "ready"}`; the host accepts it from its own iframe with origin `"null"`, as in v1.
3. The host answers `{v: 2, kind: "init", context}` with one `MessagePort`:

```json
{
  "plugin": {"id": "chat-admin", "version": "0.1.0", "name": "Chat Admin"},
  "access": [
    {"alias": "chat", "type": "flow", "actions": ["run", "sessions.read", "sessions.stop"]},
    {"alias": "conversations", "type": "key_value_table", "actions": ["read"]}
  ],
  "nav": {"path": "/conversations/c_8bfab8dd26aea13338b1c36c"},
  "theme": {"mode": "dark", "tokens": {"--es-color-background": "<css value>", "--es-font-family": "<css value>"}}
}
```

4. **Dev mode only:** a second `ready` (the dev server reloaded the page) closes the old port, streams and pending
   calls, forgets the page's sessions and runs the handshake again. In production a second `ready` is ignored and a
   second frame `load` tears the bridge down, as in v1.

## Envelope change

Events gain host-pushed topics that belong to no subscription: `{v: 2, kind: "event", topic, subscription: null, data}`.
Session events keep their `subscription` string.

## Methods (v2)

| Method | Params | Needs | What the host does | Result |
|---|---|---|---|---|
| `bridge.hello` | — | — | — | `{bridge_version, plugin, access: [{alias, type, actions}], methods}` |
| `flows.run`, `sessions.get`, `sessions.subscribe`, `sessions.unsubscribe`, `sessions.stop` | = v1 | = v1 | = v1 | = v1 |
| `kv.list` | `{table: alias, search?, ordering?, limit?, offset?}` | `read` on a `key_value_table` alias | `GET /api/key-value-table-entries/?table=<id>&ordering=&limit=&offset=[&search=]` | `{count, items: [{key, value_preview, value_truncated, created_at, updated_at}]}` |
| `kv.get` | `{table: alias, key}` | `read` on a `key_value_table` alias | `GET …/key-value-table-entries/?table=<id>&key=<key>&limit=1`, then `GET …/key-value-table-entries/<entry id>/`; answers only if the entry's table and key match | `{key, value, created_at, updated_at}` |
| `nav.changed` | `{path, replace?: bool}` | — | EpicStaff's router: `/plugins/<id>` + path (push, or replace when `replace: true`); no HTTP | `{}` |

Parameter rules:

- `search`: text ≤ 512 characters. `ordering`: `key` (default), `-key`, `updated_at`, `-updated_at`. `limit`: 1–100
  (default 20). `offset`: ≥ 0 (default 0).
- `key`: a letter or `_` followed by letters, digits or `_`, ≤ 512 characters; otherwise `bad_request` **without any
  HTTP call**.
- A missing entry, or one whose table or key does not match, is `not_found`. Entry ids, table ids and who wrote an
  entry never reach the page ([[plugins-rules]] S4, S14).

## Events

| Topic | Sent when | Data |
|---|---|---|
| `nav.navigate` | EpicStaff's URL for this plugin changed from outside the app: Back/Forward, the address bar, the plugin's left-bar button | `{path}` — the page should show that screen without reporting it back |
| `theme.changed` | EpicStaff's tokens or dark/light mode changed | `{mode, tokens}` |
| `session.message`, `session.status`, `subscription.closed` | as v1 | as v1 |

## Navigation paths

- Grammar: `^/([A-Za-z0-9\-._~%]+(/[A-Za-z0-9\-._~%]+)*)?(\?[A-Za-z0-9\-._~%=&+]*)?$`, ≤ 1024 characters, no `.` or `..`
  segment, valid `%` escapes; anything else is `bad_request`.
- The host owns history. The frame never adds history entries of its own: the SDK turns the app's `pushState` into
  `replaceState` + `nav.changed` ([[plugin-author-tooling]]), so Back/Forward move one app screen at a time.
- While the user is navigating the host, the page's `nav.changed` is ignored, so a page cannot trap the user
  ([[plugins-rules]] S15).
- A deep link to a **v1** plugin ignores the path: v1 has no handshake field for it.

## Theme tokens

Read from EpicStaff's computed styles and sent as CSS custom properties. The set is public: names are added, never
renamed or removed ([[plugins-rules]] U6). Mode is `light` when `html` or `body` has the class `my-app-light`, else
`dark`.

| Token | EpicStaff variable |
|---|---|
| `--es-color-background` | `--color-background-body` |
| `--es-color-surface` | `--color-surface-card` |
| `--es-color-surface-raised` | `--color-modals-background` |
| `--es-color-sidenav` | `--color-sidenav-background` |
| `--es-color-text`, `-secondary`, `-tertiary`, `-disabled` | `--color-text-primary`, `--color-text-secondary`, `--color-text-tertiary`, `--color-text-disabled` |
| `--es-color-accent`, `-hover`, `-active` | `--accent-color`, `--accent-color-hover`, `--accent-color-active` |
| `--es-color-input-background`, `-border`, `-placeholder` | `--color-input-background`, `--color-input-border`, `--color-input-text-placeholder` |
| `--es-color-border` | `--color-border` |
| `--es-color-divider`, `--es-color-divider-subtle` | `--color-divider-regular`, `--color-divider-subtle` |
| `--es-color-success`, `--es-color-warning`, `--es-color-error` | `--success-color`, `--color-warning`, `--color-status-error` |
| `--es-focus-ring` | `--focus-ring` |
| `--es-font-family` | `--font-family` |

## Limits (per open page)

The v1 limits (64 KB request, 10 waiting requests, 4 subscriptions, 20 `flows.run` per 60 s), plus:

| Limit | Value | Error |
|---|---|---|
| `nav.changed` calls | 120 per 60 s | `rate_limited` |
| Navigation path | 1024 characters | `bad_request` |
| `kv.list` search, `kv.get` key | 512 characters | `bad_request` |
| `kv.list` page | 100 entries | `bad_request` |

## Versioning

- `BRIDGE_TABLES = {1: BRIDGE_V1_METHODS, 2: BRIDGE_V2_METHODS}`; the backend accepts
  `SUPPORTED_BRIDGE_VERSIONS = {1, 2}` (`src/django_app/plugins/manifest.py`).
- The access policy knows which access types each version can use: a v1 page ignores `key_value_table` entries, and
  the manifest refuses a `key_value_table` entry unless `bridge` is 2.
- Once shipped, v2 is frozen like v1: new behaviour goes into v3.

## Related

- [[plugin-bridge-v1]] — [Plugin bridge v1](plugin-bridge-v1.md) (handshake, envelope, access policy, round trip)
- [[plugin-author-tooling]] — [Plugin author tooling: SDK, CLI, dev mode](plugin-author-tooling.md) (the page side)
- [[plugins-rules]] — [Plugins — rules](plugins-rules.md)
- [[plugins-architecture]] — [Plugins — architecture](plugins-architecture.md)
- [[plugin-package-format]] — [Plugin package format](plugin-package-format.md)
- [[plugins-api-contract]] — [Plugins API contract](api-contract.md)
- [[plugins-glossary]] — [Plugins glossary](plugins-glossary.md)
- [[plugins-code-map]] — [Plugins code map](code-map.md)
