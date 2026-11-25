# EpicStaff Project — Podman Deployment Guide

## 1. Clone the Repository

```bash
git clone https://github.com/EpicStaff/EpicStaff.git
cd EpicStaff/src
```

---

## 2. Environment Configuration

```bash
# For Windows Users
# sed -i 's/\r$//' .env
echo "" >> .env
echo "DB_NAME=crew" >> .env

set -a
source .env
set +a

echo $DB_NAME
# If the correct value is displayed, the setup is fine.
```
---

## 3. Create Networks and Volumes

```bash
podman network create backend-network
podman network create frontend-network
podman network create mcp-network

podman volume create sandbox_venvs
podman volume create crew_pgdata
podman volume create crew_config
podman volume create opensearch_data
```

---

## 4. Build Images

```bash
podman build -t crewdb -f ./crewdb/Dockerfile.crewdb ./crewdb
podman build -t django_app -f django_app/Dockerfile.dj .
podman build -t manager -f ./manager/Dockerfile.man .
podman build -t knowledge -f ./knowledge/Dockerfile.knowledge ./knowledge
podman build -t realtime -f ./realtime/Dockerfile.realtime ./realtime
podman build -t crew -f ./crew/Dockerfile.crew .
podman build -t sandbox_new -f ./sandbox_new/Dockerfile .
podman build -t frontend -f ../frontend/Dockerfile.fe ../frontend
```

---

## 5. Run Containers

Most containers below get the whole `.env` through `--env-file .env`, so each one holds every secret in it, including credentials of services it never talks to. `src/docker-compose.yaml` gives each service only the variables it needs; for a deployment reachable by others, prefer running that file, or trim each container's variables to the ones its compose service lists.

### Redis

```bash
podman run -d   --name redis   --network backend-network   -p ${REDIS_PORT}:${REDIS_PORT}   -v "$PWD/redis.conf":/usr/local/etc/redis/redis.conf:ro   --health-cmd="redis-cli ping"   --health-interval=5s   --health-timeout=2s   --health-retries=5   --health-start-period=5s   docker.io/library/redis:latest   redis-server /usr/local/etc/redis/redis.conf --port ${REDIS_PORT}
```

Run this from `EpicStaff/src` so `redis.conf` is found. The config file sets the pub/sub output buffer limit (`client-output-buffer-limit pubsub`). Without it Redis uses its much smaller default and can disconnect a slow subscriber when large session events arrive in bursts. The graph message stream also needs Redis 7 or newer.

---

### CrewDB

```bash
POSTGRES_PASSWORD="$DB_PASSWORD" podman run -d   --name crewdb   --network backend-network   -p ${DB_PORT}:${DB_PORT}   -v crew_pgdata:${PGDATA}   -e POSTGRES_USER=${DB_USER}   -e POSTGRES_DB=${DB_NAME}   -e POSTGRES_PASSWORD   -e PGDATA=${PGDATA}   -e DJANGO_DB_USER=${DJANGO_DB_USER}   -e DJANGO_DB_PASSWORD   -e MANAGER_DB_USER=${MANAGER_DB_USER}   -e MANAGER_DB_PASSWORD   -e KNOWLEDGE_DB_USER=${KNOWLEDGE_DB_USER}   -e KNOWLEDGE_DB_PASSWORD   -e REALTIME_DB_USER=${REALTIME_DB_USER}   -e REALTIME_DB_PASSWORD   -e SANDBOX_DB_USER=${SANDBOX_DB_USER}   -e SANDBOX_DB_PASSWORD   -e SANDBOX_DB_SCHEMA=${SANDBOX_DB_SCHEMA}   --health-cmd="bash -c 'pg_isready -U postgres || exit 1 && /usr/local/bin/custom-docker-entrypoint.sh healthcheck-users'"   --health-interval=15s   --health-timeout=10s   --health-retries=10   --health-start-period=15s   crewdb
```

---

### Django App

```bash
podman run -d   --name django_app   --network backend-network   -p 8000:8000   --env-file .env   -v crew_config:/home/user/root/app/env_config   django_app ./entrypoint.sh
```

Debug mode is controlled by `DJANGO_DEBUG`, which reaches the container through `--env-file .env`. `src/.env.example` sets it to `False`; keep it `False` for any deployment reachable by others. It has no fallback in code — if `.env` does not set it, `django_app` fails at startup.

---

### Manager

```bash
podman run -d   --name manager_container   --network backend-network   --env-file .env   -t   -i   manager
```

---

### Knowledge

```bash
podman run -d   --name knowledge   --network backend-network   --env-file .env   -t   -i   knowledge
```

---

### Realtime

```bash
podman run -d   --name realtime   --network backend-network   -p 8050:8050   --env-file .env   realtime
```

---

### Crew

```bash
podman run -d   --name crew   --network backend-network   --network mcp-network   -p 8002:8000   -v crew_config:/home/user/root/app/env_config/   --add-host host.docker.internal:host-gateway   --env-file .env   -t   -i   crew
```

Crew gets no container socket: it runs code through the sandbox's API and never starts containers. A socket mounted into it would give anything running in crew control over every container of your user.

---

### Sandbox

```bash
podman run -d   --name sandbox_new   --init   --network backend-network   -v sandbox_venvs:${SANDBOX_VENVS_DIR}   --memory 2g   --security-opt no-new-privileges   --cap-drop ALL   --cap-add SETUID   --cap-add SETGID   --cap-add CHOWN   --cap-add DAC_OVERRIDE   --cap-add FOWNER   --cap-add KILL   --env-file .env   sandbox_new ./entrypoint.sh
```

The sandbox runs user code, so it gets the same hardening as in `src/docker-compose.yaml`: every capability dropped except the few its root parent needs to switch each run to an unprivileged user, chown that run's directories and kill it on timeout, and `no-new-privileges` so user code cannot regain privileges through a setuid binary.

---

### OpenSearch (audit trail)

Needed only when `SESSION_AUDIT_TRAIL_ENABLED` or `USER_AUDIT_TRAIL_ENABLED` is `True` in `.env`; with both `False` the container exits at once.

```bash
OPENSEARCH_INITIAL_ADMIN_PASSWORD="$OPENSEARCH_PASSWORD" podman run -d   --name opensearch   --network backend-network   --init   --ulimit memlock=-1:-1   --ulimit nofile=65536:65536   -v opensearch_data:/usr/share/opensearch/data   -v "$PWD/auditor/opensearch-entrypoint.sh":/opensearch-entrypoint.sh:ro   --tmpfs /usr/share/opensearch/config/tls:uid=1000,gid=1000,mode=0700   -e SESSION_AUDIT_TRAIL_ENABLED=${SESSION_AUDIT_TRAIL_ENABLED}   -e USER_AUDIT_TRAIL_ENABLED=${USER_AUDIT_TRAIL_ENABLED}   -e discovery.type=single-node   -e bootstrap.memory_lock=true   -e OPENSEARCH_JAVA_OPTS="-Xms1g -Xmx1g"   -e OPENSEARCH_INITIAL_ADMIN_PASSWORD   --health-cmd='test -f /tmp/internal-users-synced && curl -s --cacert /usr/share/opensearch/config/tls/root-ca.pem --variable %OPENSEARCH_INITIAL_ADMIN_PASSWORD --expand-user "admin:{{OPENSEARCH_INITIAL_ADMIN_PASSWORD}}" https://localhost:9200/_cluster/health | grep -qE "\"status\":\"(green|yellow)\""'   --health-interval=10s   --health-timeout=5s   --health-retries=30   --health-start-period=300s   --entrypoint /bin/bash   docker.io/opensearchproject/opensearch:2.19.1@sha256:72fe2fc84be8295906b8efca020b46c58ed45c8da60cd9b8b49e1991e38e89a4   /opensearch-entrypoint.sh
```

Run this from `EpicStaff/src` so the entrypoint script is found. The heap is set in the command because `source .env` cannot read the unquoted `OPENSEARCH_JAVA_OPTS` line; change the heap in the command, not in `.env`. Keep two flags as they are:

- `--tmpfs ...config/tls...`: the entrypoint writes OpenSearch's TLS keys there, in memory only. Without it the container exits with an error naming that directory.
- no `-p`: OpenSearch must be reachable only from `backend-network`, never from the host.

The first start on a new `opensearch_data` volume takes several minutes: the entrypoint resets the security configuration and restarts OpenSearch once.

---

### Frontend

```bash
podman run -d   --name frontend   --network frontend-network   -p 4200:80   --read-only   --tmpfs /tmp:size=16m   --security-opt no-new-privileges   --cap-drop ALL   --sysctl net.ipv4.ip_unprivileged_port_start=0   -e API_URL=http://localhost:8000/api/   -e REALTIME_API_URL=http://localhost:8050/realtime/   frontend
```

nginx runs as the image's unprivileged `nginx` user and writes only to `/tmp`, so the root filesystem can be read-only. The `--sysctl` lets that user listen on port 80 inside the container.

---

## For Windows users
Windows Port Forwarding (WSL2)

- Get WSL IP:
```bash
hostname -I
```
- Run PowerShell as Administrator and execute:
```bash
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8000 connectaddress=<WSL_IP>
```
---

# Result 
```bash
# Open this URL in your browser
http://127.0.0.1:4200
```
---

## Notes

- Ensure all required environment variables are defined in `.env` before starting containers.
- This configuration assumes Linux environment.
