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
directly. The examples below use the short form.

Every command exits with `0` when it succeeds, `1` when the package or source breaks a rule
(the problems are printed as `loc: message` lines), and `2` when it was called wrongly.

## Lay out the source

```
weather/
├── manifest.json        the manifest
├── icon.svg             the icon the manifest names
├── spa/                 your app's sources, built into a directory of static files
├── backend/             (later versions) src/, requirements.lock, wheels/
└── database/            (later versions) migrations/NNN_<name>.sql
```

The built single-page app can live anywhere; you point `--spa-dir` at it. Its files become
`spa/` in the package, so the manifest's `spa.entry` (default `index.html`) is a path inside that
directory.

## 1. Validate

Check the source and the built app while you work:

```bash
epicstaff-plugin validate weather --spa-dir weather/spa/dist
```

```
valid: weather 0.1.0 (source)
```

Without `--spa-dir` the app is not checked. A problem looks like this:

```
manifest.id: 'admin' is reserved
package.spa/passwd: is a symbolic link
```

Rules about EpicStaff's own permission catalog (which `access` resource types and actions exist)
are checked only by EpicStaff, at upload.

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
  --key ~/keys/acme-plugins.key --out weather-0.1.0.esplugin
```

`pack` validates the source, writes `CONTENTS.json`, signs it when `--key` is given, and writes
the package. The package is **deterministic**: entries sorted by path, every timestamp
1980-01-01 00:00:00, mode 0644, deflate compression. The same files always give the same bytes,
so anyone can rebuild your package from your published sources and compare. `pack` reads the
finished package back with the same rules EpicStaff applies, and deletes it if it fails them.

`pack` copies `backend/` and `database/` as it finds them, leaving out only `__pycache__`
directories and `.DS_Store` files. It refuses symbolic links.

## 4. Sign or re-sign

To sign a package you packed without `--key`, or to replace its signature:

```bash
epicstaff-plugin sign weather-0.1.0.esplugin --key ~/keys/acme-plugins.key
```

With a password-protected minisign key, sign `CONTENTS.json` with minisign itself, using the
trusted comment EpicStaff requires, and add the signature to the package:

```bash
unzip -p weather-0.1.0.esplugin CONTENTS.json > CONTENTS.json
digest=$(shasum -a 256 CONTENTS.json | cut -d' ' -f1)
minisign -S -s ~/keys/acme-plugins.key -m CONTENTS.json \
  -t "plugin=weather version=0.1.0 contents_sha256=$digest"
zip weather-0.1.0.esplugin CONTENTS.json.minisig
```

Adding the file with `zip` keeps the package valid, though no longer byte-for-byte deterministic.

## 5. Check what EpicStaff will say

```bash
epicstaff-plugin verify weather-0.1.0.esplugin \
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
one. Installing a new version of an approved plugin is not available yet.

## Regenerate the manifest schema

`docs/plugins/reference/manifest.schema.json` is generated from the SDK; after changing the
manifest model, run from the repository root:

```bash
uv run --frozen --project src/plugin_sdk epicstaff-plugin schema --out docs/plugins/reference/manifest.schema.json
```
