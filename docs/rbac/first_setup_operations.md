# First-Time Setup — Operator Runbook

How the very first superadmin account gets created, why the HTTP path is
gated by default, and how to run the CLI command on a server, in CI, or
locally.

---

## Why the gate exists

`POST /api/auth/first-setup/` is anonymous — no authentication is possible
before any user exists. `docker-compose.yaml`'s nginx service publishes ports
80/443 as soon as `django_app` reports healthy, so on an internet-exposed
deployment the endpoint is reachable by anyone who gets there first — whoever
submits the setup form becomes the superadmin. `FIRST_SETUP_MODE` defaults to
`cli_only` so a deployment fails closed: the HTTP path is refused until an
operator explicitly opts in.

---

## The two modes

| Mode | `POST /api/auth/first-setup/` | Who can create the first superadmin | Use case |
|---|---|---|---|
| `cli_only` (default) | Refused — `403 first_setup_disabled` | `manage.py create_superadmin` only | Required for internet-exposed deployments |
| `open` | Creates the superadmin | HTTP endpoint (browser setup form) or the CLI | Local development only |

`GET /api/auth/first-setup/` always returns `200` with
`{"needs_setup": bool, "setup_mode": str}`. `needs_setup` is always `false`
under `cli_only` — even before any user exists — so the frontend shows the
login screen rather than a setup form it cannot submit.

---

## Server workflow

```
docker compose up -d
docker compose exec django_app python manage.py create_superadmin
```

The command prompts for an email, then for the password twice via `getpass`,
and confirms the two entries match. The password is never echoed to the
terminal and never enters shell history.

---

## Flags

| Flag | Purpose |
|---|---|
| `--email <email>` | Superadmin email. Omit to be prompted interactively. |
| `--password-stdin` | Read the password from stdin instead of prompting — for scripted provisioning. |
| `--org-name <name>` | Name for the organization created alongside the superadmin. Ignored if a default organization already exists. |

Scripted form:

```
echo "$PASS" | docker compose exec -T django_app \
  python manage.py create_superadmin --email ops@company.com --password-stdin
```

There is deliberately no `--password` flag: a password passed as a plain
command-line argument would leak into shell history and process listings.

---

## Organization behavior

A superadmin is always created together with an organization membership — a
superadmin with no active organization would have nowhere to operate. The
organization name resolves in this order:

1. `--org-name`, if given.
2. `settings.DEFAULT_ORGANIZATION_NAME` (env var `DEFAULT_ORGANIZATION_NAME`).
3. `"Organization"`, as a last-resort fallback.

If an organization already exists flagged as the default (`is_default=True`),
that organization is joined as-is — its name is never changed by this
command, and `--org-name` is silently ignored in that case (the command
prints a warning naming the ignored value and the existing organization's
real name).

---

## Idempotency

Re-running the command when a superadmin already exists prints
`Superadmin already exists - nothing to do.` and exits `0`. That check runs
**before** any prompting, so a repeat run never asks for a password.

---

## Troubleshooting

| Symptom | Explanation |
|---|---|
| Login page loads but no account works | `create_superadmin` has not been run yet. Run the server workflow above. |
| `403 first_setup_disabled` when submitting the setup form | Expected in `cli_only` mode (the default). Use `manage.py create_superadmin` instead. |
| Frontend shows the login screen instead of a setup form | `GET /api/auth/first-setup/` reports `needs_setup: false` whenever `FIRST_SETUP_MODE` is not `open`, by design. |

---

## Local development

`.dev.env` ships `FIRST_SETUP_MODE=open`, so local development keeps the
browser setup flow: visiting the frontend with no superadmin yet shows the
setup form, and submitting it creates the first superadmin over HTTP.

---

## See also

- [auth_endpoints.md](auth_endpoints.md) — full request/response contract
  for `GET`/`POST /api/auth/first-setup/`.
- [organization_management.md](organization_management.md) — default
  organization resolution and renaming.
- [password_recovery.md](password_recovery.md) — recovering access if a
  superadmin's password is lost after first-setup.
