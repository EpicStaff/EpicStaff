# Sign and package a plugin

This guide turns a plugin source directory into a signed `.esplugin` package a SuperAdmin can
upload. The rules a package must follow are in the [manifest and package
reference](../reference/manifest.md); what a signature means is in [Trust and
signing](../explanation/trust-and-signing.md).

## Before you package

> Plugins are meant to be open code, and EpicStaff does not check that they are. Anyone who can reach a deployment can download a plugin's frontend files. Every administrator of every deployment that installs a plugin can read the whole package, including its backend code. EpicStaff is not responsible for that exposure.

Do not put anything in a package that you would not publish: no secrets, no private keys, no
credentials in configuration files. `epicstaff-plugin pack` prints this notice every time.

## Get the command-line tool

`epicstaff-plugin` is part of the Python SDK in the EpicStaff repository, `src/plugin_sdk`
(Python 3.12 or 3.13). From an EpicStaff checkout, run it through
[uv](https://docs.astral.sh/uv/) without installing anything:

```bash
uv run --frozen --project src/plugin_sdk epicstaff-plugin --help
```

or install it as a tool once: `uv tool install ./src/plugin_sdk`, then call `epicstaff-plugin`
directly. The examples below use the short form. Use the EpicStaff version your deployment runs:
[Get the tools](../README.md#get-the-tools) has the details.

Every command exits with `0` when it succeeds, `1` when the package or source breaks a rule
(the problems are printed as `loc: message` lines), and `2` when it was called wrongly. The
[command-line reference](../reference/cli.md) lists every option and output.

## Lay out the source

```
weather/
├── manifest.json                 the manifest
├── icon.svg                      the icon the manifest names
├── spa/                          your app's sources, built into a directory of static files
├── backend/                      with a "backend" section:
│   ├── src/weather_plugin/       your Python code (the entrypoint's module is here)
│   ├── requirements.in           what the backend needs (stays in the source)
│   └── requirements.lock         compiled from it, hash-pinned
└── database/                     with a "database" section: migrations/NNN_<name>.sql
```

The built single-page app can live anywhere; you point `--spa-dir` at it. Its files become
`spa/` in the package, so the manifest's `spa.entry` (default `index.html`) is a path inside that
directory. A plugin with a backend also needs its wheels; see [A plugin with a
backend](#a-plugin-with-a-backend). A plugin with a database keeps its migrations in
`database/migrations/`; see [Write database migrations](database-migrations.md).

## 1. Validate

Check the source and the built app while you work:

```bash
epicstaff-plugin validate weather --spa-dir weather/spa/dist
```

```
valid: weather 0.7.0 (source)
```

Without `--spa-dir` the app is not checked. For a backend, `validate` checks the lock too, and
notes when it does not pin `epicstaff-plugin` yet (`pack --local-wheel` adds it). A problem looks
like this:

```
manifest.id: 'admin' is reserved
package.spa/passwd: is a symbolic link
```

Rules about EpicStaff's own permission catalog (which `access` resource types and actions exist)
and the deployment's [platform maximums](../reference/manifest.md#platform-maximums) are checked
only by EpicStaff, at upload.

## 2. Create a signing key

Once per publisher, not per plugin:

```bash
epicstaff-plugin keygen --out ~/keys/acme-plugins
```

```
key id: 41B1052724E3F245
secret key: /home/you/keys/acme-plugins.key (unencrypted; keep it private)
public key: /home/you/keys/acme-plugins.pub
PLUGINS_TRUSTED_SIGNING_KEYS entry: acme-plugins:RWRF8uMkJwWxQWjHvGCM65zBNxFclRsPWqGCgGZJfcTC4RCg+93o19KJ
```

The secret key is written readable by you only, and `keygen` never overwrites a key. The files
are minisign keys, so `minisign -G` works as well. `epicstaff-plugin` reads only unencrypted
secret keys; to keep yours password-protected, create it with `minisign -G` and sign with
`minisign` (step 4).

Give the last line to the operators of every deployment that should trust your plugins; they add
it to `PLUGINS_TRUSTED_SIGNING_KEYS` (see [Enable the plugin platform](../operator/enable-plugins.md)).
The name before the colon is only a label; they may choose their own.

## 3. Pack

```bash
epicstaff-plugin pack weather --spa-dir weather/spa/dist \
  --key ~/keys/acme-plugins.key --out weather-0.7.0.esplugin
```

`pack` validates the source, writes `CONTENTS.json`, signs it when `--key` is given, and writes
the package. The package is **deterministic**: entries sorted by path, every timestamp
1980-01-01 00:00:00, mode 0644, deflate compression. The same files always give the same bytes,
so anyone can rebuild your package from your published sources and compare. `pack` reads the
finished package back with the same rules EpicStaff applies, and deletes it if it fails them.

`pack` copies `backend/` and `database/` as it finds them, leaving out only `__pycache__`
directories, `.DS_Store` files and `backend/requirements.in`. It refuses symbolic links. It never
writes into the source directory.

## Keep secrets out of a package

Everything under `backend/` and `database/` goes into the package as it is, so keep there only
what you would publish:

- **Keep your virtual environment at the plugin's root** (`weather/.venv`), never under
  `backend/`. `pack` takes only `backend/`, `database/`, the manifest, the icon and the built app,
  so a `.venv` beside them stays out; one under `backend/` would be packed, and its symbolic links
  make `pack` refuse the source.
- **Keep runtime files out of the source altogether**, the development runtime file a SuperAdmin
  downloads for [local development](local-development.md#develop-the-backend-on-your-machine)
  included: it holds keys that act for your plugin in every organization it is granted to, and
  its secret settings. `epicstaff-plugin dev` refuses one inside the source.
- **Ignore both in version control.** The Weather sample's `plugin-samples/weather/.gitignore`
  ignores `.venv/` and `*-development-runtime.json`.

`pack`, `validate` and EpicStaff's upload read every file of the package but the wheels in
`backend/wheels/`, and refuse one that holds an EpicStaff service-account key (`esp-` and 43 more
characters, anywhere in the file's first MiB) or that is a runtime file (a JSON object with both
`service_accounts` and `secret_settings`):

```
package.backend/weather-development-runtime.json: holds an EpicStaff key or runtime file; never package it
```

The line names the file and never what was found in it. Move the file out of the source, and
if it held a key, ask a SuperAdmin to stop development on the plugin's Development tab or to
download the runtime file again: either revokes the keys it held.

## A plugin with a backend

The node installs a backend offline, so the package must carry a hash-pinned lock and a wheel
of every package in it, for the node's platform ([the lock's
rules](../reference/manifest.md#backendrequirementslock)). The Weather sample
(`plugin-samples/weather/`) is laid out this way.

### Compile the lock

List what the backend needs in `backend/requirements.in`. It must include `uvicorn`, which runs
every backend. Until `epicstaff-plugin` is published on an index, also list the SDK's own
requirements (from `src/plugin_sdk/pyproject.toml`): the SDK wheel is added at packing time, and
the lock must already pin what it needs. The sample's file, which also lists the driver for its
database:

```
fastapi
uvicorn
psycopg[binary,pool]
cryptography>=50
httpx>=0.28,<1
packaging>=24
pydantic>=2.13,<3
pyjwt>=2.10,<3
```

Compile it for the Python the manifest names, for every platform, with hashes:

```bash
cd weather
uv pip compile backend/requirements.in --universal --python-version 3.13 --generate-hashes -o backend/requirements.lock
```

Commit both files. Recompile whenever `requirements.in` changes, or to take newer versions.

### Build the SDK wheel

From an EpicStaff checkout:

```bash
uv build --project src/plugin_sdk --wheel -o dist
```

This writes `dist/epicstaff_plugin-<version>-py3-none-any.whl`.

### Pack with wheels

```bash
epicstaff-plugin pack weather --spa-dir weather/spa/dist \
  --download-wheels --local-wheel dist/epicstaff_plugin-0.1.0-py3-none-any.whl \
  --key ~/keys/acme-plugins.key --out weather-0.7.0.esplugin
```

| Option | What it does |
|---|---|
| `--download-wheels` | Downloads a binary wheel of every lock entry that applies to each target platform into the package's `backend/wheels/`. It runs `pip download` with the lock's hashes, so a file that does not match the lock is refused. Needs `pip` in the Python that runs `epicstaff-plugin` |
| `--platform <tag>` | A target platform; repeat for more. Default: `manylinux_2_28_x86_64` and `manylinux_2_28_aarch64`, the platforms EpicStaff's plugin node runs on. Older manylinux wheels (such as `manylinux2014`) are taken too, as the node runs them |
| `--local-wheel <path>` | Adds a wheel no index has, such as the SDK wheel, and appends `<name>==<version> --hash=sha256:<digest>` for it to the **packaged** lock. Repeat for more. Refused when the lock already pins that name, or does not pin something the wheel requires |

Keep both default platforms unless you know every deployment's node: a package without wheels
for a node's architecture installs on no such node.

Environment markers in the lock (`; sys_platform == 'win32'`) are evaluated for the node's
platform, not for your machine, so a Windows-only package is never downloaded and a Linux-only
one is. Your source stays as it is: the downloaded wheels and the extended lock exist only in
the package. Packing again with the same lock gives the same bytes.

Without `--download-wheels`, `pack` takes the wheels from `backend/wheels/` in your source, if
you keep them there; the two cannot be combined.

### Upload refusals to expect

A backend package is refused with `invalid_plugin` when the lock has an entry that is not an
exact, hashed pin, when it does not pin `uvicorn` and `epicstaff-plugin`, when a wheel in
`backend/wheels/` is not pinned by the lock, or when `limits` or a public path asks for more than
the deployment allows. `epicstaff-plugin validate <package>` reports all but the last before you
upload. A wheel for the wrong platform passes upload, but the node refuses to install it and
names the wheel and the platform on the plugin's Runtime tab.

## 4. Sign or re-sign

To sign a package you packed without `--key`, or to replace its signature:

```bash
epicstaff-plugin sign weather-0.7.0.esplugin --key ~/keys/acme-plugins.key
```

With a password-protected minisign key, sign `CONTENTS.json` with minisign itself, using the
trusted comment EpicStaff requires, and add the signature to the package:

```bash
unzip -p weather-0.7.0.esplugin CONTENTS.json > CONTENTS.json
digest=$(shasum -a 256 CONTENTS.json | cut -d' ' -f1)
minisign -S -s ~/keys/acme-plugins.key -m CONTENTS.json \
  -t "plugin=weather version=0.7.0 contents_sha256=$digest"
zip weather-0.7.0.esplugin CONTENTS.json.minisig
```

Adding the file with `zip` keeps the package valid, though no longer byte-for-byte deterministic.

## 5. Check what EpicStaff will say

```bash
epicstaff-plugin verify weather-0.7.0.esplugin \
  --trusted-key acme-plugins:RWRF8uMkJwWxQWjHvGCM65zBNxFclRsPWqGCgGZJfcTC4RCg+93o19KJ
```

```
trusted
key id: 41B1052724E3F245
key name: acme-plugins
```

Without `--trusted-key` (or with keys that do not include yours) it prints `untrusted` and your
key id: the package installs, with an Untrusted warning. `invalid` means the signature does not
belong to this package; EpicStaff refuses such an upload.

## 6. Hand it over

A SuperAdmin uploads the `.esplugin` file under **Workspace → Plugins**, reviews what it asks for,
and approves it. Each new upload of the same plugin, until it is approved, replaces the previous
one.

To ship a new version of an installed plugin, raise `version` in the manifest, pack and sign it
as above, and have a SuperAdmin upload it with **Upload plugin** on the Plugins list, as for a first install. Its review shows what changed
against the installed version, and approving it upgrades the plugin. A version that is not newer
than the installed one is refused. [Compatibility and versioning](../reference/compatibility-and-versioning.md)
says what a new version may change, and [Write an upgrade hook](upgrade-hook.md) how to bring each
organization to it.

A plugin with a backend is *provisioning* after approval while the node downloads it, builds its
environment and starts it, and *running* once it answers its health check. [Runtime](../reference/runtime.md)
describes what the process can rely on.

## Regenerate the manifest schema

`docs/plugins/reference/manifest.schema.json` is generated from the SDK; after changing the
manifest model, run from the repository root:

```bash
uv run --frozen --project src/plugin_sdk epicstaff-plugin schema --out docs/plugins/reference/manifest.schema.json
```
