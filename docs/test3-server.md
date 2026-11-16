# test-3: two EpicStaff instances on one server

test-3 (`82.192.91.87`, Ubuntu 26.04, 6 cores, 15 GiB RAM) runs two EpicStaff instances side by side.
Each one is capped at half the machine, so neither can starve the other or the host.

| | developer | branch |
|---|---|---|
| Deployed | on every push to `developer` | by hand: Actions → Deploy on self-hosted → server `test3` |
| URL | `http://82.192.91.87` | `http://82.192.91.87:8080` |
| Ports (HTTP / HTTPS / webhook) | 80 / 443 / 8009 | 8080 / 8443 / 8010 |
| Checkout | `/srv/epicstaff/developer` | `/srv/epicstaff/branch` |
| Containers and external volumes | `dev_*` | `branch_*` |
| Compose project | `epicstaff-dev` | `epicstaff-branch` |
| systemd slice | `epicstaff-dev.slice` | `epicstaff-branch.slice` |
| Optional stacks | audit and chat, always | audit and chat, ticked per run |
| Database | kept on every deploy, never reset | kept by default; "reset_database" empties it |

Neither instance runs plugins, which need HTTPS and a wildcard domain, and neither sends email.
Password resets use `manage.py reset_password`. Office/VPN-only access is enforced by the external
proxy in front of test-3; test-3 itself filters nothing.

## How it fits together

- **One runner.** The GitHub Actions runner `epicstaff-test-3` (repo-level, label `test3`) runs as
  the `github` user from `/home/github/actions-runner`. Its service is
  `actions.runner.EpicStaff-EpicStaff.epicstaff-test-3.service`. Both deploys use it, one at a time.
- **Per-job instance.** `.github/workflows/deploy.yaml` sets `APP_DIR` and `EPICSTAFF_SLICE` per
  job. `.github/scripts/deploy.sh` puts every container into the slice through a generated compose
  override, so a new service is capped without anyone editing anything.
- **Per-instance settings.** Each checkout has its own `src/deploy.env` (mode 600, owner `github`,
  not in git). It holds:
  - `INSTANCE_PREFIX`, `COMPOSE_PROJECT_NAME`, the ports and `PLUGINS_NETWORK_SUBNET`
    (`10.235.10.0/24` for developer, `10.235.20.0/24` for branch);
  - `COMPOSE_PROFILES`: `chat,auditor` for developer, empty for branch. Without it, `.env`'s
    `dev,chat,auditor` would apply and start mailpit. Developer also sets
    `SESSION_AUDIT_TRAIL_ENABLED`, `USER_AUDIT_TRAIL_ENABLED` and `CHAT_ENABLED` to `true`;
    `PLUGINS_ENABLED=false` and `DJANGO_EMAIL_HOST=none` on both;
  - the public URLs, `DJANGO_DEBUG=false`, `DJANGO_FIRST_SETUP_MODE=cli_only`;
  - the worker counts, set to half of the production defaults;
  - its own fresh value for every secret in `GENERATED_SECRETS` (`scripts/envtool.py`).

  `.env` is regenerated with `envtool.py --dev` on every deploy, and `deploy.env` comes after it, so
  `deploy.env` always wins.
- **Caps.** `/etc/systemd/system/epicstaff-{dev,branch}.slice` each set `CPUQuota=300%`,
  `MemoryMax=7G` and `MemorySwapMax=0`. The host has a 4 GiB `/swapfile` for itself; containers get
  none. To see an instance's usage: `systemctl status epicstaff-dev.slice`.
- **Old branches.** The branch deploy refuses a branch whose `deploy.sh` lacks the slice support.
  Merge `developer` into the branch first.

## Common tasks

- **First superadmin of the branch instance**, again after a reset:
  `docker exec -it branch_django_app python manage.py create_superadmin`.
- **Reset a password:** `docker exec -it <dev|branch>_django_app python manage.py reset_password <email>`.
- **Logs:** `cd /srv/epicstaff/<instance>/src && docker compose --env-file .env --env-file deploy.env logs -f <service>`.
  Always pass both env files: without `deploy.env`, compose uses project `src` and the wrong names.
- **Restarting by hand:** `docker compose … restart <service>` keeps the container in its slice.
  `up` or `run` by hand does not: the slice override exists only during a deploy. Re-run the
  deploy instead, or the new container runs without the cap.

## Setting up the server again

1. **Host basics.** A 4 GiB `/swapfile` with an `/etc/fstab` entry, then
   `apt-get install make jq postgresql-client`, then `docker network create mcp-network`.
   No service joins that network; the compose file only needs it to exist.
2. **Slices.** Create the two slice files above and run `systemctl daemon-reload`.
3. **Runner.**
   - Create the `github` user and add it to the `docker` group.
   - Unpack `actions-runner` into `/home/github/actions-runner`.
   - Run `./config.sh --url https://github.com/EpicStaff/EpicStaff --name epicstaff-test-3 --labels test3`.
   - Run `sudo ./svc.sh install github && sudo ./svc.sh start`.
4. **Checkouts.** `/srv/epicstaff` is owned by `github`. Clone the repo twice:
   `git clone --branch developer https://github.com/EpicStaff/EpicStaff /srv/epicstaff/<instance>`.
5. **Settings.** Write each `src/deploy.env` with the values listed above. Generate the secrets
   inside the checkout with `envtool.generate_secret(name)` for every name in
   `envtool.GENERATED_SECRETS`, appending straight to the file and never printing them.
6. **Check.** In each `src`, run `docker compose --env-file .env --env-file deploy.env config --format json | jq .name`.
   It must print `epicstaff-dev` or `epicstaff-branch`, never `src`.
7. **developer's database.** It was seeded once from test-2:
   - `pg_dump -Fc --no-owner --no-privileges` of test-2's `crewdb`, restored into
     `dev_crew_pgdata` before the first deploy. The only expected restore error is
     `schema "sandbox" already exists`: the crewdb image creates it.
   - test-2 runs `main`, which encrypts stored secrets with a key derived from
     `DJANGO_SECRET_KEY`. For the first deploy only, `deploy.env` carried test-2's
     `DJANGO_SECRET_KEY`, so migration `0291_reencrypt_secrets_master_key` moved those secrets to
     this instance's own `SECRETS_ENCRYPTION_KEY`.
   - After that deploy, the instance's fresh key went back from
     `deploy.env.fresh-django-secret-key`; the only effect is that everyone is signed out once.

**Adding a third instance:** pick a new prefix, project name, ports, subnet and slice; add a
checkout and a `deploy.env`; add a job to `deploy.yaml` that sets its `APP_DIR` and
`EPICSTAFF_SLICE`. Keep the slices' `MemoryMax` total below the host's RAM.
