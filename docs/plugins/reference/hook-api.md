# Hook API

Lifecycle hooks let a plugin backend set itself up in an organization. EpicStaff decides that a
hook runs, the deployment's plugin node calls the plugin process, and the plugin's answer
decides what happens next. This page is the contract, version 1 (`platform.hook_api: 1` in the
manifest). [Write an install hook](../how-to/install-hook.md) shows how to build one with the
[Python SDK](python-sdk.md#epicstaff_pluginhooks).

## Kinds

| Kind | Path | When | Status |
|---|---|---|---|
| `install` | `/_epicstaff/hooks/install` | A SuperAdmin granted the plugin to an organization | Supported |
| `upgrade` | `/_epicstaff/hooks/upgrade` | An organization moves to a new version of the plugin | Reserved: not called yet |
| `org_removed` | `/_epicstaff/hooks/org-removed` | An organization's grant is being purged | Reserved: not called yet |

A plugin asks for a hook in its manifest, and may shorten its timeout:

```json
"hooks": { "install": true, "timeouts_seconds": { "install": 300 } }
```

The platform maximums are 900 seconds for `install` and `org_removed` and 1800 for `upgrade`;
without a timeout of its own, a hook gets the maximum. Only a plugin with a backend can have
hooks.

## What happens on a grant

| The plugin's package | The grant starts as | Then |
|---|---|---|
| Has no backend | `active` | — |
| Has a backend, no install hook | `active`, with a service account | — |
| Has a backend and an install hook | `granting`, with a service account | The hook succeeds: `active`. It fails or times out: `install_failed`, with its error shown to the SuperAdmin, who can retry it |

While the grant is `granting` nobody in the organization can open the plugin, and the plugin's
service account already works, so the hook can create what the plugin needs. A retry runs the
same job again with the next attempt number.

## The call

The node calls the plugin process over the loopback interface, never from outside: nginx does
not forward `/_epicstaff/` on any plugin address.

```
POST /_epicstaff/hooks/install
X-EpicStaff-Hook: <assertion>
Content-Type: application/json

{"format":1,"job_id":41,"attempt":1,"kind":"install","org":{"id":3,"name":"Acme"},"plugin":{"identifier":"weather","version":"0.4.0"},"previous_version":null}
```

The node makes the call only when the process is running and healthy and its
[runtime file](runtime.md#runtime-file) already holds the organization's service-account key.
It runs one hook at a time per plugin.

### The body

The model is `epicstaff_plugin.contracts.hook_api.HookRequest`; at most 16 KiB.

| Field | Meaning |
|---|---|
| `format` | `1` |
| `job_id` | The job. A retry keeps it |
| `attempt` | 1 on the first call, one more on each retry |
| `kind` | `install`, `upgrade` or `org_removed`; always the kind of the path |
| `org` | `{id, name}` of the organization |
| `plugin` | `{identifier, version}`: the plugin and the version the hook runs for |
| `previous_version` | The version the organization ran before an upgrade; `null` for the other kinds |

### The assertion

`X-EpicStaff-Hook` is a compact JWS that EpicStaff signs (EdDSA over Ed25519) with the key it
signs [gateway contexts](gateway-context.md) with. Its header is
`{"alg": "EdDSA", "typ": "epicstaff-plugin-hook+jwt", "kid": "<key id>"}`; the `typ` keeps the
two kinds of token apart. Its claims (`HookAssertionClaims`):

| Claim | Value |
|---|---|
| `iss` | EpicStaff's public origin, the runtime file's `issuer` |
| `aud` | The plugin's id |
| `iat`, `exp` | When it was signed, and that time plus the hook's timeout plus 60 seconds |
| `jti` | 32 hex characters |
| `kind`, `job_id`, `attempt`, `org_id` | The body's |
| `body_sha256` | The hex SHA-256 of the exact body bytes |

EpicStaff signs a new assertion for every attempt, just before the node makes the call.

### Verification

`python -m epicstaff_plugin.serve` checks every hook call before any of your code runs. A call
passes when all of these hold:

1. there is exactly one `X-EpicStaff-Hook` header;
2. its signature verifies with the key its `kid` names (a key the runtime file does not list yet
   is downloaded as for gateway contexts, at most once per 30 seconds);
3. `typ` is `epicstaff-plugin-hook+jwt`, `aud` is the plugin, `iss` is the runtime file's issuer,
   and it has not expired (30 seconds of leeway for clocks);
4. `kind` is the kind of the path it was posted to;
5. the body is at most 16 KiB and its SHA-256 is `body_sha256`;
6. the body is a valid `HookRequest` whose `job_id`, `attempt`, `kind`, organization and plugin
   are the assertion's.

Another plugin on the node can reach your port but cannot forge an assertion, and cannot reuse
one with another body. `epicstaff_plugin.hooks.verify_hook_assertion` runs the same checks
outside the runner.

## The answer

| Answer | Outcome |
|---|---|
| `200 {"status":"done"}` | The hook succeeded |
| Anything else | The hook failed. With a JSON body `{"status":"failed","error":{"message":"…"}}`, the message is what the SuperAdmin sees (at most 2000 characters); otherwise they see `HTTP <status>`, `timed out after <n> s` or `could not connect: <reason>` |

The SDK's runner answers:

| Case | Status | Body |
|---|---|---|
| The handler returned | 200 | `{"status":"done"}` |
| The handler raised | 500 | `{"status":"failed","error":{"message":"<first line of the exception, at most 2000 characters>"}}` |
| The call failed verification | 401 | `{"status":"failed","error":{"message":"hook assertion rejected: <reason>"}}` |
| No handler for the kind | 501 | `{"status":"failed","error":{"message":"this plugin has no <kind> hook"}}` |
| A method other than `POST` on a hook path | 405 | — |

The rejection reasons are `missing`, `ambiguous`, `malformed`, `wrong_type`, `unknown_key`,
`bad_signature`, `expired`, `not_yet_valid`, `wrong_audience`, `wrong_issuer`,
`invalid_claims`, `wrong_kind`, `body_too_large`, `body_digest_mismatch`, `invalid_body` and
`body_mismatch`.

## What a hook may do

A hook calls EpicStaff with the organization's [service account](../how-to/call-epicstaff-from-the-backend.md),
alone: never on behalf of a person, since nobody can use the plugin in the organization yet.
EpicStaff lets it do exactly what the manifest's `access` declares, and records everything it
creates as owned by the plugin. Flows that hold a schedule, webhook or Telegram trigger need
`flows: use`; without it EpicStaff refuses the trigger with 403.

## Your duties

- **Idempotency.** A job can run more than once: a SuperAdmin retries a failed one, a restart of
  the plugin during the call fails it, and a timed-out attempt may still be running when the
  next one starts. Do the work at most once per `job_id`: look up what an earlier attempt made
  (by a mark you put on it, or in your own records) before making it again. Never adopt
  something by its name alone: a person may have made one of that name.
- **One organization at a time.** The SDK's runner runs at most one handler per organization at
  a time in the process, so a retry waits for a slow earlier attempt to end.
- **A clear error.** The first line of the exception is what the SuperAdmin reads next to the
  grant. Say what failed and what would fix it.
- **Within the timeout.** After the timeout the node stops waiting and the hook fails.
