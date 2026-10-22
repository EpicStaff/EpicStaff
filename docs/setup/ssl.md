# SSL (HTTPS) for nginx

nginx serves plain HTTP on port 80 unless `NGINX_SSL_MODE="on"` in `src/.env`. With
SSL on, nginx includes the HTTPS server block (`src/nginx/templates/ssl-on.snippet.template`),
which reads the certificate and key from `/etc/nginx/certs/` — mounted read-only from
`src/nginx/certs/` in `src/docker-compose.yaml`:

```
src/nginx/certs/fullchain.pem   # certificate
src/nginx/certs/privkey.pem     # private key
```

For a public deployment, put a CA-issued certificate there (e.g. from Let's Encrypt).

## Self-signed certificate for local testing

Run from the repo root, replacing `example.com` with your `NGINX_SERVER_NAME`. It needs
only Docker — `openssl` runs inside a throwaway Alpine container.

Bash / Git Bash:

```bash
docker run --rm -v "$(pwd)/src/nginx/certs:/certs" -w /certs alpine \
  sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout privkey.pem -out fullchain.pem -subj '/CN=example.com'"
```

PowerShell:

```powershell
docker run --rm -v "${PWD}/src/nginx/certs:/certs" -w /certs alpine `
  sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout privkey.pem -out fullchain.pem -subj '/CN=example.com'"
```

Then set `NGINX_SSL_MODE="on"` in `src/.env` and recreate nginx so it picks up the
new value (`restart` does not re-read `.env`):

```bash
cd src
docker compose -f docker-compose.yaml --env-file ./.env up -d epicstaff-nginx
```

Browsers will warn about the self-signed certificate; that is expected.

Note that `src/.env.example` ships with `NGINX_SSL_MODE=on` (production default),
while `python scripts/envtool.py --dev` renders `off`.

## HSTS

`NGINX_HSTS_ENABLED` decides whether nginx sends `Strict-Transport-Security:
max-age=31536000; includeSubDomains`. It doesn't depend on `NGINX_SSL_MODE`. It has no
production default, so `src/.env` must set it:

- `true` for any deployment users reach over HTTPS.
- `false` if any subdomain of your domain is served only over plain HTTP. With `true`,
  browsers refuse to open such a subdomain for a year.
- `false` for a VPN-only instance with an internal certificate. With `true`, an expired or
  mismatched certificate blocks the site in browsers, with no way to click through, until
  it is replaced.

## Behind a load balancer

If a load balancer in front of nginx handles TLS, set `NGINX_SSL_MODE=off`. That turns off
only TLS in nginx and its http→https redirect, which would loop behind a load balancer. HSTS
still follows `NGINX_HSTS_ENABLED`, so set it to `true` and make sure the load balancer
passes the `Strict-Transport-Security` header through to the browser.
