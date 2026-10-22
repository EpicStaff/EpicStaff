# Command-line tool (`epicstaff-plugin`)

`epicstaff-plugin` checks, packs and signs plugins, and runs a plugin's backend on your machine
against a local EpicStaff. It is part of the [Python SDK](python-sdk.md), in the EpicStaff
repository at `src/plugin_sdk` (Python 3.12 or 3.13), and is not on an index yet:
[Get the tools](../README.md#get-the-tools) says how to get it.

From an EpicStaff checkout, run it through [uv](https://docs.astral.sh/uv/) without installing
anything:

```bash
uv run --frozen --project src/plugin_sdk epicstaff-plugin --help
```

or install it once with `uv tool install ./src/plugin_sdk` and call `epicstaff-plugin` directly.
`epicstaff-plugin dev` is the exception: it imports your backend, so it runs from your plugin's
own virtual environment, where your backend's lock is installed
([Develop the backend on your machine](../how-to/local-development.md#develop-the-backend-on-your-machine)).

| Command | What it does |
|---|---|
| [`validate`](#epicstaff-plugin-validate) | Checks a source directory or a built package against the rules EpicStaff applies at upload |
| [`pack`](#epicstaff-plugin-pack) | Builds a deterministic `.esplugin` package, with the backend's wheels, signed or not |
| [`keygen`](#epicstaff-plugin-keygen) | Creates a signing key pair |
| [`sign`](#epicstaff-plugin-sign) | Adds or replaces a package's signature |
| [`verify`](#epicstaff-plugin-verify) | Says whether a package installs as Trusted or Untrusted |
| [`schema`](#epicstaff-plugin-schema) | Writes the manifest's JSON Schema |
| [`dev`](#epicstaff-plugin-dev) | Runs your plugin's backend on your machine, for an EpicStaff in development mode |

## Exit codes and output

Every command exits with:

| Code | Meaning |
|---|---|
| `0` | It succeeded. `verify` also exits `0` for an Untrusted package; `dev` when you stop it |
| `1` | The source or package breaks a rule, or `dev` could not start |
| `2` | It was called wrongly: a missing file, a bad option, an output that already exists |

A rule a package breaks is printed on standard output as one `loc: message` line per problem,
with the same `loc` EpicStaff's upload answers with ([Manifest and package
format](manifest.md#errors)):

```
manifest.id: 'admin' is reserved
package.spa/passwd: is a symbolic link
```

A wrong call is printed on standard error as `epicstaff-plugin: error: <message>`. Every command
takes `--help`.

## `epicstaff-plugin validate`

Usage: `epicstaff-plugin validate <target> [--spa-dir <directory>]`

| Argument | Meaning |
|---|---|
| `<target>` | A plugin source directory, or a built `.esplugin` file |
| `--spa-dir <directory>` | The built single-page app, checked with a source directory. Not allowed with a package (exit `2`) |

```bash
epicstaff-plugin validate plugin-samples/weather --spa-dir plugin-samples/weather/spa/dist
epicstaff-plugin validate weather-0.7.0.esplugin
```

It checks every rule of [Manifest and package format](manifest.md) that does not depend on a
deployment: the deployment's permission catalog and its platform maximums are checked only by
EpicStaff, at upload. That includes the secret scan: a file that holds an EpicStaff key or a
runtime file is refused ([Keep secrets out of a package](../how-to/sign-and-package.md#keep-secrets-out-of-a-package)).

| Output | When |
|---|---|
| `valid: <id> <version> (source)` | A source directory passed |
| `valid: <id> <version> (signature present)` or `(signature absent)` | A package passed. Whether the signature is trusted is `verify`'s question |
| `note: the single-page app was not checked; pass the built app with --spa-dir` | A source with an `spa` section, without `--spa-dir` |
| `note: backend/requirements.lock does not pin epicstaff-plugin; pack with --local-wheel <epicstaff-plugin wheel> to add it` | A source whose lock does not pin the SDK yet. A package must pin it |

## `epicstaff-plugin pack`

Usage: `epicstaff-plugin pack <source> --out <file> [--spa-dir <directory>] [--key <secret key>] [--download-wheels] [--platform <tag>]... [--local-wheel <wheel>]...`

| Argument | Meaning |
|---|---|
| `<source>` | The plugin source directory |
| `--out <file>` | Required. The package to write. An existing file is replaced |
| `--spa-dir <directory>` | The built single-page app; required when the manifest has `spa`. Its files become `spa/` in the package |
| `--key <secret key>` | An unencrypted minisign secret key to sign with. Without it the package is unsigned |
| `--download-wheels` | Downloads a binary wheel of every `backend/requirements.lock` entry for each target platform into the package's `backend/wheels/`, with `pip download` and the lock's hashes. Needs `pip` in the Python that runs `epicstaff-plugin`. Refused (exit `2`) when the source keeps its own `backend/wheels/` |
| `--platform <tag>` | A Linux wheel platform to download for; repeat for more. Only with `--download-wheels`. Default: `manylinux_2_28_x86_64` and `manylinux_2_28_aarch64`, the platforms EpicStaff's plugin node runs on |
| `--local-wheel <wheel>` | A wheel no index has, such as the SDK wheel, added to `backend/wheels/` and pinned in the **packaged** lock. Repeat for more |

```bash
epicstaff-plugin pack plugin-samples/weather --spa-dir plugin-samples/weather/spa/dist --download-wheels --local-wheel dist/epicstaff_plugin-0.1.0-py3-none-any.whl --key ~/keys/acme-plugins.key --out weather-0.7.0.esplugin
```

It prints the [open-code notice](../README.md#before-you-start) first, then validates the source,
writes `CONTENTS.json`, signs it when `--key` is given, writes the package, and reads it back
with the rules EpicStaff applies. On success it prints
`packed <file> (<id> <version>, <n> files, unsigned)` or `(…, signed with key <key id>)`. A
problem at any step is printed as `loc: message` lines, exit `1`, and no package is left behind.

The package is deterministic, it copies `backend/` and `database/` as it finds them apart from
`__pycache__`, `.DS_Store` and `backend/requirements.in`, and it never writes into the source:
[Sign and package a plugin](../how-to/sign-and-package.md) has the details.

## `epicstaff-plugin keygen`

Usage: `epicstaff-plugin keygen --out <prefix>`

| Argument | Meaning |
|---|---|
| `--out <prefix>` | Required. Writes `<prefix>.key`, the secret key, readable by you only, and `<prefix>.pub`, the public key. Exit `2` when either file exists: `keygen` never overwrites a key |

```bash
epicstaff-plugin keygen --out ~/keys/acme-plugins
```

```
key id: 41B1052724E3F245
secret key: /home/you/keys/acme-plugins.key (unencrypted; keep it private)
public key: /home/you/keys/acme-plugins.pub
PLUGINS_TRUSTED_SIGNING_KEYS entry: acme-plugins:RWRF8uMkJwWxQWjHvGCM65zBNxFclRsPWqGCgGZJfcTC4RCg+93o19KJ
```

The files are minisign keys. The name in the last line is the prefix's file name, with any
character but letters, digits, `.`, `_` and `-` turned into `-`, at most 64 characters; it is
only a label, and operators may choose their own.

## `epicstaff-plugin sign`

Usage: `epicstaff-plugin sign <package> --key <secret key>`

| Argument | Meaning |
|---|---|
| `<package>` | A built `.esplugin` file |
| `--key <secret key>` | Required. An unencrypted minisign secret key |

```bash
epicstaff-plugin sign weather-0.7.0.esplugin --key ~/keys/acme-plugins.key
```

It replaces the package's signature, if it has one, in place, and prints
`signed <package> with key <key id>`. A package that breaks a rule, its old signature aside, is
refused with `loc: message` lines, exit `1`. To sign with a password-protected key, use
minisign itself: [Sign or re-sign](../how-to/sign-and-package.md#4-sign-or-re-sign).

## `epicstaff-plugin verify`

Usage: `epicstaff-plugin verify <package> [--trusted-key <name>:<public key>]...`

| Argument | Meaning |
|---|---|
| `<package>` | A built `.esplugin` file |
| `--trusted-key <name>:<public key>` | A key to trust, as an entry of `PLUGINS_TRUSTED_SIGNING_KEYS`; repeat for more. A malformed entry is exit `2` |

```bash
epicstaff-plugin verify weather-0.7.0.esplugin --trusted-key acme-plugins:RWRF8uMkJwWxQWjHvGCM65zBNxFclRsPWqGCgGZJfcTC4RCg+93o19KJ
```

| Output | Exit | Meaning |
|---|---|---|
| `trusted`, `key id: <key id>`, `key name: <name>` | `0` | Signed with one of the keys, and the signature verifies |
| `untrusted`, `key id: <key id>` | `0` | Signed with a key not given; EpicStaff installs it with an Untrusted warning |
| `untrusted`, `key id: none (unsigned)` | `0` | Not signed |
| `invalid`, `key id: <key id>`, `reason: <reason>` | `1` | The signature does not belong to this package; EpicStaff refuses it |
| `invalid`, then `loc: message` lines | `1` | The package breaks a rule |

[Trust and signing](../explanation/trust-and-signing.md) explains each result.

## `epicstaff-plugin schema`

Usage: `epicstaff-plugin schema --out <file>`

| Argument | Meaning |
|---|---|
| `--out <file>` | Required. Where to write the manifest's JSON Schema. Exit `2` when it cannot be written |

```bash
uv run --frozen --project src/plugin_sdk epicstaff-plugin schema --out docs/plugins/reference/manifest.schema.json
```

It prints `wrote <file>`. [`manifest.schema.json`](manifest.schema.json) is generated this way.

## `epicstaff-plugin dev`

Usage: `epicstaff-plugin dev <source> --runtime-file <file> [--port <port>] [--host <address>] [--no-reload] [--database-url <url>] [--apply-migrations]`

Runs your plugin's backend from its source, on your machine, for an EpicStaff whose plugin
development mode is on. A SuperAdmin then points the installed plugin at it, and EpicStaff sends
the plugin's backend requests there instead of to the plugin node.
[Local development](../how-to/local-development.md#develop-the-backend-on-your-machine) walks
through it.

```bash
epicstaff-plugin dev plugin-samples/weather --runtime-file ~/weather-dev/weather-development-runtime.json --port 8001
epicstaff-plugin dev plugin-samples/weather --runtime-file ~/weather-dev/weather-development-runtime.json --database-url postgresql://weather_app:<password>@127.0.0.1:5433/weather_development --apply-migrations
```

| Argument | Meaning |
|---|---|
| `<source>` | The plugin source directory, with a manifest that has a `backend` section (exit `2` otherwise). A source that breaks the package rules, or whose entrypoint module is not under `backend/src`, is exit `1`, with `loc: message` lines. The source is scanned for secrets as `pack` scans a package: a file that holds an EpicStaff key or a runtime file is exit `2` |
| `--runtime-file <file>` | Required. The development runtime file a SuperAdmin downloaded from the plugin's Development tab. It must lie outside `<source>`, also after following symbolic links (exit `2`: "keep it outside your plugin's source: it holds keys and secret settings"), and be for this plugin: its `plugin.identifier` must be the manifest's `id` (exit `2`). One that cannot be read as a runtime file is exit `1` |
| `--port <port>` | Where the backend listens, 1024–65535. Default `8001` |
| `--host <address>` | The address it listens on: an IP address or `localhost`. Default `127.0.0.1` |
| `--no-reload` | Turn reloading off. By default the backend restarts whenever a file under `<source>/backend/src` changes |
| `--database-url <url>` | A `postgresql://` URL (exit `2` for anything else) of a local database for the backend ([A local database](#a-local-database)). Only for a manifest with a `database` section (exit `2` otherwise). Without it the backend gets no database variables |
| `--apply-migrations` | Apply the plugin's migrations to that database before starting. Needs `--database-url` (exit `2` otherwise) |

| Exit | When |
|---|---|
| `0` | You stopped it (Ctrl-C or SIGTERM) |
| `1` | It could not start: the source or the runtime file is invalid; a package the backend's lock pins is not installed in this environment ("install the backend's lock in this environment", naming the missing ones), uvicorn among them; the database is unsuitable or a migration failed; or uvicorn could not serve, for example because the port is taken |
| `2` | A usage error, above |

### What it runs

It serves your backend exactly as the plugin node composes it, with `epicstaff_plugin.serve`'s
`create_app()`: the health check, then the hook paths, then the gateway-context check, then your
app ([Python SDK](python-sdk.md#epicstaff_pluginserve)). Every request but the health check and
the hook calls needs a gateway context EpicStaff signed, so the backend answers only what comes
through EpicStaff's gateway. uvicorn runs it with one worker, proxy headers ignored, no `Server`
header and lifespan events on. uvicorn is your backend's dependency, not the SDK's: install your
backend's lock in the environment you run `dev` from.

The backend's environment is yours, with these set:

| Variable | Value |
|---|---|
| `PORT` | `--port` |
| `EPICSTAFF_PLUGIN_IDENTIFIER`, `EPICSTAFF_PLUGIN_VERSION`, `EPICSTAFF_PLUGIN_ENTRYPOINT` | From the source's manifest |
| `EPICSTAFF_PLUGIN_RUNTIME_FILE` | The full path of `--runtime-file` |
| `EPICSTAFF_API_URL`, `EPICSTAFF_PUBLIC_URL`, `EPICSTAFF_PLUGIN_PUBLIC_URL` | From the runtime file |
| `PYTHONPATH` | `<source>/backend/src` first |
| `DATABASE_URL`, `EPICSTAFF_PLUGIN_DB_CONNECTIONS` | Only with `--database-url`: the URL, and the manifest's `limits.db_connections`, else 5 |

and `EPICSTAFF_PLUGIN_LISTEN_FD` removed, so the backend binds `--host` and `--port` itself, as
well as `DATABASE_URL` and `EPICSTAFF_PLUGIN_DB_CONNECTIONS` when `--database-url` is not given.
Everything else, proxy variables included, is inherited from your shell.

### What it prints

Once, at start, on standard output:

```
Weather (weather) 0.7.0 from plugin-samples/weather
Installed in EpicStaff: 0.7.0
Backend: http://127.0.0.1:8001
Database: postgresql://weather_app:***@127.0.0.1:5433/weather_development (applied 3 migrations: 001_weather.sql, 002_retention.sql, 003_place_conditions.sql; 0 already applied)

In EpicStaff: Plugins → Weather → Development → Backend port 8001 → Save
Then open http://epicstaff.localhost/plugins/weather

Keys for: Acme (3), Cobalt (5)
Download the file again to the same path after granting another organization or after a suspension.

How this backend differs from the plugin node:
  - no outbound-host allow-list: requests leave through this machine's network
  - the database is the one you pass, not the plugin's (its login role also owns the tables)
  - hooks run on the installed version
  - public paths, settings, access and permissions are the installed version's
```

When they apply, it adds a note under `Installed in EpicStaff` when the source's version is not
the installed one, and at the end: a note when the source's public paths differ from the installed
version's, or the environment's packages from the lock's; a warning when the runtime file's
EpicStaff API address is not on this machine, or when the file can be read by other users; and,
on Linux, that the backend must listen on the Docker bridge address with `--host`. Then uvicorn's
own log follows.

It never prints or logs a key, a secret setting or the runtime file, and shows a database URL with
its password masked.

### A local database

A development backend never reaches the plugin's own database on the deployment. With
`--database-url` it gets a database you run yourself, PostgreSQL 16 or later, set up like the
plugin node sets one up, with two roles:

- a login role `<name>_app`, which owns the database, and so also owns everything your
  migrations create in it;
- a role `<name>_job` that cannot log in, granted to the login role `WITH INHERIT FALSE, SET
  TRUE`, so the SDK's `job_transaction` can switch to it.

`dev` refuses a database whose roles are set up otherwise, and a login role that is a superuser
or may bypass row-level security ("row-level security would not apply as on EpicStaff"), and
prints the SQL that creates suitable roles and the database. [A database for the development
backend](../how-to/local-development.md#a-database-for-the-development-backend) shows it.

With `--apply-migrations`, it applies the files of `<source>/database/migrations/` as the node
does: in name order, each in a transaction of its own, with the role placeholders replaced by
the quoted role names, `${owner_role}` and `${app_role}` by the login role and `${job_role}` by
the job role. It records them in the same ledger, `_epicstaff.migrations`: a file applied with
the same content is skipped, and one whose content changed after it was applied is refused,
naming the file. A failing file is rolled back alone and stops the run, with
`<name> line <n>: [<SQLSTATE>] <message>`. It uses psycopg 3, from the same environment, and says
how to install it when it is missing (exit `1`).
