# Manifest and package format

Every plugin is one `.esplugin` file: a zip holding a `manifest.json` that describes the plugin,
the files the manifest implies, and a `CONTENTS.json` that lists them all. This page is the
reference for both. [Sign and package a plugin](../how-to/sign-and-package.md) shows how to build
one; [Trust and signing](../explanation/trust-and-signing.md) explains the signature.

EpicStaff checks every rule below when a SuperAdmin uploads a package, and
`epicstaff-plugin validate` checks the same rules on your machine: both use the one definition in
the Python SDK (`epicstaff_plugin.contracts.manifest`). The machine-readable form is
[`manifest.schema.json`](manifest.schema.json) (JSON Schema 2020-12, generated from that
definition). The schema cannot express the rules that tie two fields together, such as "`access`
needs `backend`"; those are marked *cross-field* below.

## What this version of EpicStaff installs

The manifest format accepts every field on this page, so a manifest does not change when EpicStaff
gains features. This version installs **frontend-only plugins**: a package that declares
`backend` or `database` is refused with `plugin_feature_unavailable`, and one with neither `spa`
nor `backend` (nothing to install) with `invalid_plugin`. Because `access`, `public_paths`,
`outbound_hosts`, `settings`, `limits` and enabled hooks all need a backend, a plugin
installable today has an `spa` section, leaves those empty or out, and turns every hook off.

## Example

The Weather sample (`plugin-samples/weather/manifest.json`):

```json
{
  "manifest_version": 1,
  "id": "weather",
  "version": "0.1.0",
  "name": "Weather",
  "description": "Forecasts for the places your organization cares about.",
  "publisher": { "name": "EpicStaff" },
  "icon": "icon.svg",
  "platform": { "frame_protocol": 1, "gateway_context": 1, "hook_api": 1 },
  "spa": { "entry": "index.html" },
  "user_permissions": [
    { "action": "read", "description": "Open Weather and see forecasts.", "defaults": { "org_admin": true, "member": true, "viewer": false } }
  ]
}
```

A manifest with every section filled in (a plugin with a backend, which later EpicStaff versions
install):

```json
{
  "manifest_version": 1,
  "id": "weather",
  "version": "1.0.0",
  "name": "Weather",
  "description": "Forecasts for the places your organization cares about.",
  "publisher": { "name": "EpicStaff" },
  "icon": "icon.svg",
  "platform": { "frame_protocol": 1, "gateway_context": 1, "hook_api": 1 },
  "spa": { "entry": "index.html" },
  "backend": { "python": "3.13", "entrypoint": "weather_plugin.app:app" },
  "database": {},
  "access": [
    { "resource_type": "flows", "actions": ["read", "create", "update", "delete", "use"], "reason": "Creates the Weather forecast flow and runs it for you." },
    { "resource_type": "files", "actions": ["read", "create"], "reason": "Stores forecast reports." }
  ],
  "user_permissions": [
    { "action": "read", "description": "Open Weather and see forecasts.", "defaults": { "org_admin": true, "member": true, "viewer": true } },
    { "action": "update", "description": "Add and remove saved places.", "defaults": { "org_admin": true, "member": true, "viewer": false } },
    { "action": "delete", "description": "Change the organization's Weather settings.", "defaults": { "org_admin": true, "member": false, "viewer": false } }
  ],
  "public_paths": [
    { "path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0 }
  ],
  "outbound_hosts": [
    { "host": "geocoding-api.open-meteo.com", "reason": "City search." }
  ],
  "settings": [
    { "key": "units", "type": "enum", "label": "Units", "description": "Units for every organization.", "required": true, "default": "metric", "values": ["metric", "imperial"] }
  ],
  "limits": { "memory_mb": 256, "db_connections": 5, "statement_timeout_seconds": 10, "requests_per_minute": 120, "cpu_priority": "normal" },
  "hooks": { "install": true, "upgrade": true, "org_removed": true, "timeouts_seconds": { "install": 300 } }
}
```

## General rules

- `manifest.json` is one UTF-8 JSON object. A key that appears twice, `NaN` and `Infinity` are
  refused.
- **Unknown fields are refused**, at every level (`"additionalProperties": false`). A misspelt
  field is an error, not a silently ignored setting.
- **Types are strict:** `1` is not `"1"`, and `true` is not `"true"` or `1`.
- Text fields (`name`, `description`, `reason`, `label`) must not be blank and must not contain
  control characters such as line breaks.

## Fields

| Field | Type | Required | Rules |
|---|---|---|---|
| `manifest_version` | `1` | yes | Only `1`. |
| `id` | string | yes | `^[a-z][a-z0-9-]{0,30}[a-z0-9]$` (2–32 characters). Reserved: `www`, `api`, `admin`, `plugins`, `epicstaff`, `static`, `postgres`, `public`, `packages`, and anything starting with `pg`. The plugin's address is `<id>.<plugin base domain>`, so the id never changes between versions. |
| `version` | string | yes | [SemVer 2.0](https://semver.org/) with ASCII digits, at most 64 characters: `1.2.3`, `1.0.0-beta.1`, `1.0.0+build.5`. |
| `name` | string | yes | 1–64 characters. Shown in the left bar. |
| `description` | string | yes | 1–500 characters. |
| `publisher` | object | yes | `name` (1–64 characters, required) and `url` (optional, `https://` only, no credentials). Shown as *claimed* unless the package is Trusted. |
| `icon` | string | yes | `icon.svg` or `icon.png`, a file at the package root. See [Icon](#icon). |
| `platform` | object | yes | `frame_protocol`, `gateway_context` and `hook_api`, each `1`: the versions of the platform contracts the plugin is written for. |
| `spa` | object | no | The plugin's single-page app. `entry` (default `index.html`) is a path inside `spa/` that must exist in the package. |
| `backend` | object | no | `python`: `"3.12"` or `"3.13"`; `entrypoint`: `module.path:attribute` of an ASGI app, whose module is `backend/src/<module/path>.py` or `backend/src/<module/path>/__init__.py`. Not installed by this version. |
| `database` | `{}` | no | Present when the plugin needs its own database; takes no fields. Not installed by this version. |
| `access` | array | no (default `[]`) | What the plugin's backend may do in EpicStaff; see [access](#access). *Cross-field:* non-empty `access` needs `backend`. |
| `user_permissions` | array | yes | What people may do with the plugin; see [user_permissions](#user_permissions). |
| `public_paths` | array | no (default `[]`) | Backend paths reached without an EpicStaff login. Each: `path` under `/api/` (`/api/<segment>[/…]`, no `.` or `..` segment, at most 512 characters, distinct), `match` `exact` or `prefix`, `methods` (distinct, from `GET HEAD POST PUT PATCH DELETE OPTIONS`), `rate_limit_per_minute` 1–6000, `max_body_kb` 0–20480. *Cross-field:* needs `backend`. |
| `outbound_hosts` | array | no (default `[]`) | Hosts the backend may call, over HTTPS on port 443 only. Each: `host` is a lower-case DNS name or `*.` and a name (no IP address, no port, distinct) and `reason` (1–200 characters). *Cross-field:* needs `backend`. |
| `settings` | array | no (default `[]`) | Deployment-wide settings a SuperAdmin fills in; see [settings](#settings). *Cross-field:* needs `backend`. |
| `limits` | object | no | `memory_mb` 64–8192, `db_connections` 1–100, `statement_timeout_seconds` 1–600, `requests_per_minute` 1–6000, `cpu_priority` `normal` or `low`; all five required when present. EpicStaff may still cap them lower. *Cross-field:* needs `backend`. |
| `hooks` | object | no (default all off) | `install`, `upgrade`, `org_removed` (booleans) and optional `timeouts_seconds` with `install` ≤ 900, `upgrade` ≤ 1800, `org_removed` ≤ 900. *Cross-field:* any hook turned on needs `backend`. |

### access

Each entry is `{resource_type, actions, reason}` and names an EpicStaff permission the plugin's
backend needs, in the same terms as the Roles page:

- `resource_type`: a resource type of EpicStaff's permission catalog, such as `flows`, `files`
  or `secrets`. One entry per type.
- `actions`: at least one, distinct, from `read create update delete export use`; each must be an
  action that resource type has and that a role can be given. The catalog differs between
  EpicStaff versions, so EpicStaff checks this at upload (`epicstaff-plugin validate` checks only
  the form). `GET /api/permissions/catalog/` on an EpicStaff lists its resource types and their
  actions.
- `reason`: 1–200 characters, shown to the SuperAdmin who approves the plugin.

Running flows and writing schedule, webhook or Telegram trigger nodes needs `flows: use`; the
review warns when `flows` has `create` or `update` without `use`.

### user_permissions

Each entry is `{action, description, defaults}`: one action people can be given on the plugin.

- `action`: one of `read`, `create`, `update`, `delete`, `export`, `use` (shown as View, Create,
  Edit, Delete, Export, Use), each at most once. `read` (View) is required: without it nobody sees
  the plugin.
- `description`: 1–200 characters saying what the action means inside your plugin.
- `defaults`: `{org_admin, member, viewer}`, all three booleans: whether each built-in role gets
  the action. A role that gets any action must also get `read`. Organizations cannot change what
  built-in roles get; other roles get nothing in this version.

### settings

Each entry is `{key, type, label, description, required, default, values}`:

- `key`: `^[a-z][a-z0-9_]{0,63}$`, distinct.
- `type`: `string`, `text`, `integer`, `boolean`, `url`, `enum` or `secret`.
- `label` 1–64 characters, `description` 1–500 characters, `required` boolean.
- `values`: for `enum` only, and required there: distinct strings of 1–64 characters.
- `default`: optional, of the setting's type (an integer for `integer`, a boolean for `boolean`,
  an `http(s)` URL for `url`, one of `values` for `enum`). A `secret` has no default.

## Package layout

A package is a zip named `<id>-<version>.esplugin` by convention. Paths inside it are fixed; the
manifest does not name them.

```
manifest.json
CONTENTS.json
CONTENTS.json.minisig                 optional: the signature
icon.svg | icon.png                   the one the manifest names
spa/<entry>, spa/**                   with "spa"
backend/src/**                        with "backend"
backend/requirements.lock             with "backend" (required)
backend/wheels/*.whl                  with "backend"
database/migrations/NNN_<name>.sql    with "database"; NNN = three digits, distinct
```

Any other file is refused, as are `spa/`, `backend/` or `database/` files without their manifest
section.

### Caps and path rules

| Rule | Value |
|---|---|
| Package size | At most the deployment's `PLUGINS_MAX_PACKAGE_MB` (300 MiB by default) |
| Entries | At most 10 000. Directory entries are not needed and are ignored |
| Uncompressed size | At most 1 GiB in total and 256 MiB per file. A file larger than 1 MiB uncompressed may not expand more than 100 times (uncompressed size above 100 × compressed size); smaller files may compress as well as they like |
| Compression | Stored or deflate; no encryption |
| Paths | UTF-8 in NFC form, `/`-separated and relative: no `..` or `.` segment, no empty segment, no leading `/`, no `\`, no drive letter, no control character, at most 1024 bytes. No two paths may differ only in case, and no file may also be a folder of another (`spa/a` and `spa/a/b.js`), case ignored |
| Entry types | Regular files only: symbolic links and special files are refused |
| SPA | At most 2000 files and 50 MiB in total |
| Icon | At most 64 KiB |

### Icon

`icon.png` must be a PNG image. `icon.svg` must be UTF-8 XML with an `<svg>` root, and inert:
no `<script>` or `<foreignObject>` element, no event-handler attribute (`onload`, `onclick`, …),
no DOCTYPE or entity declaration, no stylesheet processing instruction, and no reference outside
the file (an `href` or `src` that is not `#…`, a CSS `url(…)` that is not `url(#…)`, or
`@import`). EpicStaff only ever shows the icon as an image.

### CONTENTS.json

Lists every file of the package except itself and its signature, so that signing this one file
covers the whole package:

```json
{"files":[{"path":"icon.svg","sha256":"<64 hex>","size":1543},{"path":"manifest.json","sha256":"<64 hex>","size":812},{"path":"spa/index.html","sha256":"<64 hex>","size":640}],"format":1,"plugin_id":"weather","version":"0.1.0"}
```

- `format` is `1`; `plugin_id` and `version` equal the manifest's `id` and `version`.
- `files` is sorted by `path`; each entry gives the file's size in bytes and its lower-case
  SHA-256. Every listed file must exist with that size and digest, and every file must be listed.
- The stored bytes must be the canonical form, exactly what Python's
  `json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as
  UTF-8 gives, without a trailing newline.

`epicstaff-plugin pack` writes it for you.

### CONTENTS.json.minisig

Optional. A [minisign](https://jedisct1.github.io/minisign/) signature of `CONTENTS.json`
(pre-hashed, the default of minisign 0.10 and later) whose trusted comment is exactly:

```
plugin=<id> version=<version> contents_sha256=<SHA-256 of CONTENTS.json, lower-case hex>
```

[Trust and signing](../explanation/trust-and-signing.md) explains how EpicStaff reads it.

## Errors

An upload that breaks a rule is answered `400` with code `invalid_plugin` and one entry per
problem in `errors`. `epicstaff-plugin validate` prints the same problems as `loc: message`
lines.

```json
{
  "status_code": 400,
  "code": "invalid_plugin",
  "message": "The plugin package is invalid. 2 problems found.",
  "errors": [
    { "loc": "manifest.id", "message": "'admin' is reserved" },
    { "loc": "package.spa/app.js", "message": "is not listed in CONTENTS.json" }
  ]
}
```

`loc` starts with the part of the package the problem is in:

| Prefix | Refers to | Example |
|---|---|---|
| `manifest` | a field of `manifest.json`, with list indexes | `manifest.user_permissions[1].action` |
| `contents` | a field of `CONTENTS.json` | `contents.files[3].sha256` |
| `signature` | `CONTENTS.json.minisig` | `signature` |
| `package` | the archive as a whole, or one file in it after the dot | `package`, `package.spa/app.js` |

Other upload answers: `invalid_signature` (a signature that does not belong to the package),
`plugin_feature_unavailable` (a `backend` or `database` section, listed in `errors`),
`package_too_large` (413) and `plugin_upgrade_unavailable` (409, the plugin already has an
approved version; installing a new version is not available yet).

Approving a package checks the stored file again before anything is published: it must still be
the uploaded file (otherwise `409 package_file_mismatch`: upload it again), it must still pass
every rule on this page, and its signature is judged with the trusted keys as they are at that
moment (see [Trust and signing](../explanation/trust-and-signing.md)).

## Review warnings

The SuperAdmin's review shows these next to the package:

| Code | When |
|---|---|
| `untrusted_package` | The package is not signed by a key the deployment trusts |
| `flows_use_missing` | `access` gives `flows` `create` or `update` but not `use` |
| `wildcard_outbound_host` | An outbound host starts with `*.`; one warning per such host |
