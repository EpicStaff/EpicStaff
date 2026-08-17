:: Idempotent: generates the signing keys on first run, preserves them afterwards.
call "%~dp0create_env.bat"

docker volume create crew_config
docker volume create crew_pgdata
docker volume create sandbox_venvs

docker compose --env-file ./../.env --env-file ./../.signing.env -f ./../docker-compose.yaml up
pause
