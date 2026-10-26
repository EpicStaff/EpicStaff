# Trust and signing

Every plugin package installs as either **Trusted** or **Untrusted**. This page explains what
decides it, what it does and does not protect, and why packages are signed the way they are.

## Trusted is a label, not a permission

A Trusted plugin and an Untrusted plugin can do exactly the same things once approved. The label
answers one question for the SuperAdmin reviewing a package: *did someone this deployment trusts
publish exactly these files?*

- **Trusted:** the package is signed with a key listed in the deployment's
  `PLUGINS_TRUSTED_SIGNING_KEYS`, and the signature verifies. The review shows the key's name,
  and the publisher shown in the manifest is backed by that key.
- **Untrusted:** the package is unsigned, or signed with a key the deployment does not list. It
  can still be installed, but the review shows a warning, the publisher is shown as *claimed*,
  and approving needs an explicit acknowledgement that the package runs unverified code.

Neither label checks what the code does. Installing a plugin means trusting its code; the
protection is that only a SuperAdmin installs plugins, after reading what each package asks for.

## What EpicStaff decides from a signature

| The package | Result |
|---|---|
| has no `CONTENTS.json.minisig` | Untrusted, signature *absent* |
| is signed with a key the deployment does not list | Untrusted, signature *unknown key*; the review shows the key id, so the SuperAdmin can ask the publisher about it. The trusted comment must still name this package, or the upload is refused |
| is signed with a listed key, both signatures verify and the trusted comment names this package | Trusted, signature *valid*, with the key's name |
| is signed with a listed key and any of these checks fails | Refused: `invalid_signature` |
| has a signature file that is not a minisign signature | Refused: `invalid_plugin`, at `signature` |

An Untrusted result is never a reason to refuse an upload; a signature that is present but wrong
always is. A broken signature on a package means someone changed it after signing, and EpicStaff
does not guess which part to believe.

The decision is made twice: at upload, for the review, and again when the SuperAdmin approves,
with the keys listed at that moment. A package signed with a key the operator has removed since
the upload is Untrusted at approval and needs the acknowledgement; one signed with a key listed
since then is Trusted. The review shows the newer result.

## What the signature covers

The signature is over `CONTENTS.json` only, and `CONTENTS.json` lists every other file of the
package with its size and SHA-256. EpicStaff checks each file against that list before it looks
at the signature, so one signature covers the whole package: change one byte of any file and
either the list no longer matches or the signature no longer verifies.

The signature's *trusted comment* is itself signed, and must read exactly

```
plugin=<id> version=<version> contents_sha256=<SHA-256 of CONTENTS.json>
```

so a valid signature cannot be moved onto another plugin, another version of the same plugin, or
another `CONTENTS.json`. EpicStaff checks the comment even for keys it does not list.

## Why minisign

The format is [minisign](https://jedisct1.github.io/minisign/)'s: Ed25519 signatures over a
BLAKE2b-512 hash of the file, with a signed trusted comment.

- **It works offline.** Verifying needs only the public keys the operator listed. A deployment
  installs plugins without reaching any outside service, and keyless schemes that depend on an
  online log or certificate authority could not offer that.
- **Keys are small text.** A public key is one line (`RW…`), easy to publish next to a plugin's
  sources and to paste into `PLUGINS_TRUSTED_SIGNING_KEYS`.
- **Two tools work.** `epicstaff-plugin keygen`, `sign` and `verify` write and read the same
  files as the reference `minisign` tool, so a publisher can keep a password-protected key and
  sign with `minisign`, and anyone can check a signature without EpicStaff's tools.

Only pre-hashed signatures (the default of minisign 0.10 and later) are accepted.

## Keys

- **One key per publisher**, not per plugin. Operators decide whom they trust, not which plugin.
- **Keep the secret key off build servers you do not control.** Anyone holding it can publish
  packages every deployment that lists your key shows as Trusted.
- **A key id is 16 hexadecimal digits** (`41B1052724E3F245`), shown as minisign shows it. The
  review shows it for every signed package, so a SuperAdmin can compare it with the id your
  public key file names.
- **Rotating a key:** create a new one, ask operators to add it next to the old one, sign new
  packages with it, then ask them to remove the old one. Packages already approved stay
  installed; the label matters at review time.
- **A leaked key:** ask operators to remove it from `PLUGINS_TRUSTED_SIGNING_KEYS` at once. From
  then on, packages signed with it install as Untrusted, including uploads still waiting for
  approval.

For operators, `PLUGINS_TRUSTED_SIGNING_KEYS` is a comma-separated list of `<name>:<public key>`
entries (`none` lists no key). A name is 1–64 letters, digits, `.`, `_` or `-`; names and keys
must not repeat. EpicStaff refuses to start with a malformed list (start-up check
`plugins.E004`, see [Enable the plugin platform](../operator/enable-plugins.md)).
