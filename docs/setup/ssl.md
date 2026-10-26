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
while `python scripts/envtool.py --dev` renders `off`. With `on` and no certificate, nginx
doesn't start: its log (`docker logs epicstaff-nginx`) names the missing file. Add the
certificate as above, or set `NGINX_SSL_MODE=off` only if a load balancer in front of nginx
handles TLS (see below).

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

nginx then receives plain HTTP, and it tells Django the browser's scheme in
`X-Forwarded-Proto`. It believes the load balancer's `X-Forwarded-Proto` only from the
addresses in `NGINX_TRUSTED_PROXIES`. List your load balancer there:

```
NGINX_TRUSTED_PROXIES=192.0.2.10                # one load balancer
NGINX_TRUSTED_PROXIES=192.0.2.10, 192.0.2.11    # several
NGINX_TRUSTED_PROXIES=192.0.2.0/28              # a range of them
```

If you leave it out, Django is told every request came over plain HTTP, and the absolute links
it builds start with `http://`, such as avatar URLs and the flow assistant's stream URL. The
stream URL is then an `http://` link on an HTTPS page: browsers block it as mixed content, and
the assistant's answers never arrive.

- **List the address nginx sees the load balancer connect from.** That is not always the load
  balancer's public address. To find it, open the site through the load balancer and read the
  first field of the latest lines of `docker logs epicstaff-nginx`. Where Docker relays the
  published port through its own proxy (Docker Desktop, for one), that field is a Docker
  address, such as the network's gateway `172.18.0.1`, for every client. Trusting it then means
  trusting every client that can reach port 80, so make sure only the load balancer can. That
  address can also change when the containers are recreated; a load balancer on the same Docker
  network as nginx connects from an address of its own instead.
- **List nothing wider than the load balancer.** Any address you list can tell Django a
  request came over HTTPS.
- **The load balancer must set `X-Forwarded-Proto` itself, to `http` or `https`, on every
  request and every listener it has.** Deleting the client's `X-Forwarded-Proto` is not enough.
  nginx accepts header names with underscores, and it reads `X_Forwarded_Proto` and
  `X-Forwarded_Proto` as the same header. A load balancer that only strips `X-Forwarded-Proto`
  by name passes a client's `X_Forwarded_Proto: https` on, and nginx believes it. When the load
  balancer sets the header itself, a client's underscore spelling only adds a second value. Two
  values, or any value other than `http` or `https`, count as not set, and nginx sends its own
  scheme, `http`.
- **Only IPv4 addresses and CIDRs are accepted**, separated by commas. nginx stops at startup
  on any other value, and its log (`docker logs epicstaff-nginx`) says why. It also refuses a
  `/0` range, which is every client, and a CIDR with host bits set, such as `192.0.2.5/24`.
  Write `192.0.2.5` for that one address, or `192.0.2.0/24` for the whole range.
- **If you enable nginx's real-IP module** (`set_real_ip_from`, see
  [plugins: behind another proxy](../plugins/operator/enable-plugins.md#behind-another-proxy-or-load-balancer)),
  list the load balancer in `NGINX_TRUSTED_PROXIES` as well. nginx decides trust by the address
  the connection comes from, not by the client address the module puts in its place.

Recreate nginx after changing it (`restart` does not re-read `.env`):

```bash
cd src
docker compose -f docker-compose.yaml --env-file ./.env up -d epicstaff-nginx
```

## Without a load balancer

If nothing sits in front of nginx, set `NGINX_TRUSTED_PROXIES=none`. nginx then always sends
Django its own scheme, `https` with `NGINX_SSL_MODE=on`, whatever a client claims in its own
`X-Forwarded-Proto`. `python scripts/envtool.py --dev` renders `none`; `src/.env.example` has no
production default, so every deployment chooses.

## Upgrading

`NGINX_TRUSTED_PROXIES` is a new required variable. `docker compose` refuses to start until
`src/.env` sets it. `make env-update` adds a `# NGINX_TRUSTED_PROXIES=<enter your value>`
placeholder; replace it with `none`, or with your load balancer's addresses as described above.
