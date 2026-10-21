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
gains features. This version installs plugins with a single-page app, a Python backend, or both.
A package that declares `database` is refused with `plugin_feature_unavailable`, and one with
neither `spa` nor `backend` (nothing to install) with `invalid_plugin`.

A backend runs as its own process on the deployment's plugin node ([Runtime](runtime.md)). In
this version it serves its `public_paths` and the requests of people logged in to the plugin
through EpicStaff's gateway, reads its `settings` and `limits`, calls EpicStaff's API within its
`access` ([Service account API](service-account-api.md)), and runs its `install` hook when an
organization is granted the plugin ([Hook API](hook-api.md)). `outbound_hosts` and the `upgrade`
and `org_removed` hooks are accepted and shown at review, but nothing uses them yet.

## Example

The Weather sample (`plugin-samples/weather/manifest.json`), a page and a backend with one public
path and two settings:

```json
{
  "manifest_version": 1,
  "id": "weather",
  "version": "0.2.0",
  "name": "Weather",
  "description": "Forecasts for the places your organization cares about.",
  "publisher": { "name": "EpicStaff" },
  "icon": "icon.svg",
  "platform": { "frame_protocol": 1, "gateway_context": 1, "hook_api": 1 },
  "spa": { "entry": "index.html" },
  "backend": { "python": "3.13", "entrypoint": "weather_plugin.app:app" },
  "user_permissions": [
    { "action": "read", "description": "Open Weather and see forecasts.", "defaults": { "org_admin": true, "member": true, "viewer": false } }
  ],
  "public_paths": [
    { "path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0 }
  ],
  "settings": [
    { "key": "units", "type": "enum", "label": "Units", "description": "Units every forecast is shown in.", "required": true, "default": "metric", "values": ["metric", "imperial"] },
    { "key": "forecast_api_token", "type": "secret", "label": "Forecast API token", "description": "Token for a forecast service that needs one; the sample works without it.", "required": false }
  ],
  "limits": { "memory_mb": 256 }
}
```

A manifest with every section filled in (a plugin with a database, which later EpicStaff versions
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
| `backend` | object | no | `python`: `"3.12"` or `"3.13"`; `entrypoint`: `module.path:attribute` of an ASGI app, whose module is `backend/src/<module/path>.py` or `backend/src/<module/path>/__init__.py`. Its files are under `backend/` ([backend/requirements.lock](#backendrequirementslock)); [Runtime](runtime.md) says how it is run. |
| `database` | `{}` | no | Present when the plugin needs its own database; takes no fields. Not installed by this version. |
| `access` | array | no (default `[]`) | What the plugin's backend may do in EpicStaff; see [access](#access). *Cross-field:* non-empty `access` needs `backend`. |
| `user_permissions` | array | yes | What people may do with the plugin; see [user_permissions](#user_permissions). |
| `public_paths` | array | no (default `[]`) | Backend paths reached without an EpicStaff login. Each: `path` under `/api/` (`/api/<segment>[/…]`, no `.` or `..` segment, at most 512 characters, distinct), `match` `exact` or `prefix`, `methods` (distinct, from `GET HEAD POST PUT PATCH DELETE OPTIONS`), `rate_limit_per_minute` 1–6000, `max_body_kb` 0–20480, each at most the deployment's maximum ([Platform maximums](#platform-maximums)). *Cross-field:* needs `backend`. |
| `outbound_hosts` | array | no (default `[]`) | Hosts the backend may call, over HTTPS on port 443 only. Each: `host` is a lower-case DNS name or `*.` and a name (no IP address, no port, distinct) and `reason` (1–200 characters). *Cross-field:* needs `backend`. |
| `settings` | array | no (default `[]`) | Deployment-wide settings a SuperAdmin fills in; see [settings](#settings). *Cross-field:* needs `backend`. |
| `limits` | object | no | `memory_mb` 64–8192, `db_connections` 1–100, `statement_timeout_seconds` 1–600, `requests_per_minute` 1–6000, `cpu_priority` `normal` or `low`. Each is optional: one left out (or `null`) gets the platform default, and each is at most the deployment's maximum ([Platform maximums](#platform-maximums)). A SuperAdmin may lower them per plugin. *Cross-field:* needs `backend`. |
| `hooks` | object | no (default all off) | `install`, `upgrade`, `org_removed` (booleans) and optional `timeouts_seconds` with `install` ≤ 900, `upgrade` ≤ 1800, `org_removed` ≤ 900. A hook without a timeout gets that maximum. This version runs the `install` hook ([Run code when an organization gets your plugin](../how-to/install-hook.md)); the other two are reserved. *Cross-field:* any hook turned on needs `backend`. |

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
- `reason`: 1–200 characters, shown to the SuperAdmin who approves the plugin, and to the Org
  Admins of every organization the plugin is granted to.

Six resource types cannot be declared, because their endpoints never accept a plugin's
credentials: `organizations`, `memberships`, `roles`, `api_keys`, `audit` and `chats`. An upload
that declares one is refused with `invalid_plugin` at `manifest.access[<i>].resource_type`
("'audit' cannot be declared by a plugin").

`access` is everything the plugin's backend may do in an organization it is granted to, and
nothing more: its service account there holds exactly these actions, whoever the call is made
for. Running flows and writing schedule, webhook or Telegram trigger nodes needs `flows: use`;
the review warns when `flows` has `create` or `update` without `use`. `secrets` has no `update`:
replace a secret by creating a new one and deleting the old. See
[Declare what your backend may do](../how-to/declare-access.md).

### user_permissions

Each entry is `{action, description, defaults}`: one action people can be given on the plugin.

- `action`: one of `read`, `create`, `update`, `delete`, `export`, `use` (shown as View, Create,
  Edit, Delete, Export, Use), each at most once. `read` (View) is required: without it nobody sees
  the plugin.
- `description`: 1–200 characters saying what the action means inside your plugin.
- `defaults`: `{org_admin, member, viewer}`, all three booleans: whether each built-in role gets
  the action. Organizations cannot change what built-in roles get; a custom role gets only the
  actions an Org Admin gives it on the Roles page. The built-in Superadmin role, which the
  first SuperAdmin's membership holds, gets the `org_admin` defaults while its holder is a
  SuperAdmin; someone no longer a SuperAdmin gets nothing through it. Being a SuperAdmin gives no
  action by itself: a SuperAdmin who is no member of an organization cannot use a plugin there.
- *Cross-field:* a built-in role that gets any action must also get `read`.
- *Cross-field:* the built-in roles build on each other. For every action, `viewer: true` needs
  `member: true`, and `member: true` needs `org_admin: true` (refused at
  `manifest.user_permissions[<i>].defaults`). People assign roles only up to their own plugin
  actions, so without this an Org Admin could not assign Member.

### settings

Each entry is `{key, type, label, description, required, default, values}`:

- `key`: `^[a-z][a-z0-9_]{0,63}$`, distinct.
- `type`: `string`, `text`, `integer`, `boolean`, `url`, `enum` or `secret`.
- `label` 1–64 characters, `description` 1–500 characters, `required` boolean.
- `values`: for `enum` only, and required there: distinct strings of 1–64 characters.
- `default`: optional, of the setting's type (an integer for `integer`, a boolean for `boolean`,
  an `http(s)` URL for `url`, one of `values` for `enum`). A `secret` has no default.

### Platform maximums

The schema bounds above are the most any deployment may allow. Each deployment sets its own
maximums, and an upload that asks for more is refused with `invalid_plugin` at the field
(`manifest.limits.memory_mb`, `manifest.public_paths[0].max_body_kb`, ...). A limit the manifest
leaves out, or a backend without `limits`, gets the platform default, capped by the maximum.

| Field | Deployment maximum (variable) | Maximum by default | Platform default |
|---|---|---|---|
| `limits.memory_mb` | `PLUGINS_MAX_PROCESS_MEMORY_MB` | 1024 | 256 |
| `limits.db_connections` | `PLUGINS_MAX_DB_CONNECTIONS` | 20 | 5 |
| `limits.statement_timeout_seconds` | `PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS` | 60 | 30 |
| `limits.requests_per_minute` | `PLUGINS_MAX_REQUESTS_PER_MINUTE` | 600 | 120 |
| `limits.cpu_priority` | — | — | `normal` |
| `public_paths[].rate_limit_per_minute` | `PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE` | 120 | — |
| `public_paths[].max_body_kb` | `PLUGINS_MAX_REQUEST_BODY_MB` × 1024 | 20480 | — |

`epicstaff-plugin validate` checks only the schema bounds; the deployment's maximums are checked
at upload. [Limits](limits.md) says which limits this version enforces and how.

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

### backend/requirements.lock

The node installs a backend offline, from the package alone:
`pip install --no-index --find-links backend/wheels --require-hashes --only-binary=:all: -r backend/requirements.lock`.
So the lock is a pip requirements file that holds nothing but exact pins with hashes:

- every requirement is `name==version`, optionally with extras and an environment marker
  (`; sys_platform == 'win32'`), and has at least one `--hash=sha256:<64 hex digits>`;
- no other option (`--index-url`, `-e`, `-r`, `--find-links`, ...) and no URL or path
  requirement;
- it pins `uvicorn` and `epicstaff-plugin`, which run every backend
  ([Runtime](runtime.md#how-the-backend-is-started));
- every file in `backend/wheels/` is a wheel whose name and version the lock pins.

`uv pip compile requirements.in --universal --generate-hashes` writes such a lock; [Sign and
package a plugin](../how-to/sign-and-package.md#a-plugin-with-a-backend) shows how, and how `pack`
downloads the wheels. Wheels must match the node: CPython of the manifest's `backend.python`
on Linux, `manylinux_2_28` or older, `x86_64` or `aarch64`. A wheel built for another platform is
refused when the node installs the backend, naming the wheel and the platform.

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
`plugin_feature_unavailable` (a `database` section, listed in `errors`),
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
