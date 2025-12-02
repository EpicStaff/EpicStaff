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
## 3. Podman Socket Configuration

```bash
podman system service -t 0 &

echo $XDG_RUNTIME_DIR/podman/podman.sock

# Set the variable (use the path from the previous command)
PODMAN_SOCKET="<output_from_echo>" 
```
Usually, it will be:
```bash
PODMAN_SOCKET="/run/user/1000/podman/podman.sock"
```
---

## 4. Create Networks and Volumes

```bash
podman network create backend-network
podman network create frontend-network
podman network create mcp-network

podman volume create sandbox_venvs
podman volume create sandbox_executions
podman volume create crew_pgdata
podman volume create crew_config
```

---

## 5. Build Images

```bash
podman build -t crewdb -f ./crewdb/Dockerfile.crewdb ./crewdb
podman build -t django_app -f django_app/Dockerfile.dj .
podman build -t manager -f ./manager/Dockerfile.man .
podman build -t knowledge -f ./knowledge/Dockerfile.knowledge ./knowledge
podman build -t realtime -f ./realtime/Dockerfile.realtime ./realtime
podman build -t crew -f ./crew/Dockerfile.crew .
podman build -t sandbox -f ./sandbox/Dockerfile.sandbox .
podman build -t frontend -f ../frontend/Dockerfile.fe ../frontend
```

---

## 6. Run Containers

### Redis

```bash
podman run -d   --name redis   --network backend-network   -p ${REDIS_PORT}:${REDIS_PORT}   --health-cmd="redis-cli ping"   --health-interval=5s   --health-timeout=2s   --health-retries=5   --health-start-period=5s   docker.io/library/redis:latest
```

---

### CrewDB

```bash
podman run -d   --name crewdb   --network backend-network   -p ${DB_PORT}:${DB_PORT}   -v crew_pgdata:${PGDATA}   -e POSTGRES_DB=${POSTGRES_DB}   -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD}   -e PGDATA=${PGDATA}   -e DB_MANAGER_USER=${DB_MANAGER_USER}   -e DB_MANAGER_PASSWORD=${DB_MANAGER_PASSWORD}   -e DB_KNOWLEDGE_USER=${DB_KNOWLEDGE_USER}   -e DB_KNOWLEDGE_PASSWORD=${DB_KNOWLEDGE_PASSWORD}   -e DB_REALTIME_USER=${DB_REALTIME_USER}   -e DB_REALTIME_PASSWORD=${DB_REALTIME_PASSWORD}   -e DB_CREW_USER=${DB_CREW_USER}   -e DB_CREW_PASSWORD=${DB_CREW_PASSWORD}   --health-cmd="bash -c 'pg_isready -U postgres || exit 1 && /usr/local/bin/custom-docker-entrypoint.sh healthcheck-users'"   --health-interval=15s   --health-timeout=10s   --health-retries=10   --health-start-period=15s   crewdb
```

---

### Django App

```bash
podman run -d   --name django_app   --network backend-network   -p 8000:8000   --env-file .env   -e DEBUG=${DEBUG:-True}   -v crew_config:/home/user/root/app/env_config   django_app ./entrypoint.sh
```

---

### Manager

```bash
podman run -d   --name manager_container   --network backend-network   --env-file .env   -p 8001:8000   -t   -i   -v /var/run/podman/podman.sock:/var/run/docker.sock   manager
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
podman run -d   --name crew   --network backend-network   --network mcp-network   -p 8002:8000   -v crew_config:/home/user/root/app/env_config/   --add-host host.docker.internal:host-gateway   --env-file .env   -t   -i   -v /run/user/1000/podman/podman.sock:/var/run/docker.sock   crew
```

---

### Sandbox

```bash
podman run -d   --name sandbox   --network backend-network   -v sandbox_venvs:${BASE_VENV_PATH}   -v sandbox_executions:${OUTPUT_PATH}   -v ${CREW_SAVEFILES_PATH}:${CONTAINER_SAVEFILES_PATH}   --env-file .env   -t   -i   sandbox
```

---

### Frontend

```bash
podman run -d   --name frontend   --network frontend-network   -p 4200:80   -v ../frontend-config/frontend-config.json:/usr/share/nginx/html/config.json:ro   frontend
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
- Verify that Podman socket path is correct for your user (`$PODMAN_SOCKET`).
- This configuration assumes Linux environment.
