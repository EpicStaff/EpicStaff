# Installing EpicStaff from a release bundle

This folder is everything a release needs to run: the compose file with every EpicStaff image
pinned by digest, the configuration it mounts (nginx, redis and the optional profiles), and the
tool that writes `src/.env`. No clone of the source is needed.

Run every command below from this folder (`epicstaff-<tag>/`) unless it says otherwise.

## Requirements

- Docker with the Compose plugin.
- Python 3.12 with `pyyaml==6.0.3` to run the setup tool, or none at all if you run it in the
  `python` container shown below.

## Install

### 1. Write `src/.env`

The setup tool asks for the public URL, how HTTPS is handled, which features to turn on and how
long to keep data, and generates every password and key. Keep `src/.env` private and back it up:
the databases are created with the credentials in it.

```bash
# With Python on the host
python scripts/envtool.py --setup

# Only Docker: macOS / Linux
docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/repo" -w /repo python:3.12.10-slim sh -c "pip install -q --user --disable-pip-version-check pyyaml==6.0.3 && python scripts/envtool.py --setup"
```

```powershell
# Only Docker: Windows (PowerShell)
docker run --rm -it -v "${PWD}:/repo" -w /repo python:3.12.10-slim sh -c "pip install -q --root-user-action=ignore --disable-pip-version-check pyyaml==6.0.3 && python scripts/envtool.py --setup"
```

When it asks which release to pull, give this bundle's tag. The compose file pins every image by
digest, so it runs exactly the images of this release either way.

### 2. Add certificates (only when nginx serves HTTPS itself)

If you chose that nginx terminates HTTPS, put the certificate chain and its private key in
`src/nginx/certs/` as `fullchain.pem` and `privkey.pem`. nginx refuses to start without them.
With the plugin platform on, also add the wildcard certificate for the plugins' parent domain
(for example `*.plugins.example.com`) as `plugins-fullchain.pem` and `plugins-privkey.pem`; see
`docs/plugins/operator/enable-plugins.md` in the EpicStaff repository at this release's tag.

### 3. Create the external volumes and network

Compose expects these to exist. If `INSTANCE_PREFIX` in `src/.env` is not empty, put its value in
front of each volume name (for example `branch-crew_pgdata`).

```bash
docker volume create sandbox_venvs
docker volume create crew_pgdata
docker volume create media_data
docker volume create opensearch_data
docker network create mcp-network
```

The same commands work in PowerShell.

### 4. Start

```bash
cd src
docker compose up -d
```

Docker pulls each `ghcr.io/epicstaff/*` image by the digest pinned in `docker-compose.yaml`;
nothing is built. Open the public URL you gave the setup tool.

## Upgrading to a newer release

Each release unpacks into its own `epicstaff-<tag>/` folder, and the setup tool keeps your
credentials only when it finds your existing `src/.env`.

1. Back up `src/.env` and your volumes. Migrations change the database on start, and there is no
   downgrade path.
2. Download and verify the new bundle, then unpack it next to the old one.
3. Copy your configuration into the new folder:

   ```bash
   cp epicstaff-<old-tag>/src/.env epicstaff-<new-tag>/src/.env
   cp -r epicstaff-<old-tag>/src/nginx/certs/. epicstaff-<new-tag>/src/nginx/certs/
   ```

   ```powershell
   Copy-Item epicstaff-<old-tag>/src/.env epicstaff-<new-tag>/src/.env
   Copy-Item epicstaff-<old-tag>/src/nginx/certs/* epicstaff-<new-tag>/src/nginx/certs/
   ```

4. In the new folder, run the setup tool again (step 1 of Install). It keeps the credentials and
   offers the settings the new release added.
5. Start from the new folder:

   ```bash
   cd epicstaff-<new-tag>/src
   docker compose up -d
   ```

Two things break an upgrade:

- **Running the setup tool without the copied `src/.env`.** It then generates new credentials,
  and the existing databases reject them.
- **Starting compose from a folder not named `src`.** Unless `COMPOSE_PROJECT_NAME` is set in
  `src/.env`, compose names the project after the folder, and the volumes it created itself
  (redis, storage, chat and plugin databases) carry over only under the same project name.
