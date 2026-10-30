# EpicStaff Project — Podman Deployment Guide

## 1. Clone the Repository

```bash
git clone https://github.com/EpicStaff/EpicStaff.git
cd EpicStaff/src
```

---

## 2. Environment Configuration

```bash
export $(grep -v '^#' .env | xargs)

# For Windows Users
# sed -i 's/\r$//' .env
# export $(grep -v '^#' .env | xargs)
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
podman run -d   --name crewdb   --network backend-network   -p ${DB_PORT}:${DB_PORT}   -v crew_pgdata:${PGDATA}   -e POSTGRES_USER=${DB_USER}   -e POSTGRES_DB=${DB_NAME}   -e POSTGRES_PASSWORD=${DB_PASSWORD}   -e PGDATA=${PGDATA}   -e MANAGER_DB_USER=${MANAGER_DB_USER}   -e MANAGER_DB_PASSWORD=${MANAGER_DB_PASSWORD}   -e KNOWLEDGE_DB_USER=${KNOWLEDGE_DB_USER}   -e KNOWLEDGE_DB_PASSWORD=${KNOWLEDGE_DB_PASSWORD}   -e REALTIME_DB_USER=${REALTIME_DB_USER}   -e REALTIME_DB_PASSWORD=${REALTIME_DB_PASSWORD}   -e SANDBOX_DB_USER=${SANDBOX_DB_USER}   -e SANDBOX_DB_PASSWORD=${SANDBOX_DB_PASSWORD}   -e SANDBOX_DB_SCHEMA=${SANDBOX_DB_SCHEMA}   --health-cmd="bash -c 'pg_isready -U postgres || exit 1 && /usr/local/bin/custom-docker-entrypoint.sh healthcheck-users'"   --health-interval=15s   --health-timeout=10s   --health-retries=10   --health-start-period=15s   crewdb
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

### Frontend

```bash
podman run -d   --name frontend   --network frontend-network   -p 4200:80   -e API_URL=http://localhost:8000/api/   -e REALTIME_API_URL=http://localhost:8050/realtime/   frontend
```
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
