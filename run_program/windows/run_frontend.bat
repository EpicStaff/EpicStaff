:: Compose interpolates the whole file before selecting a service, so the
:: django_app signing keys must resolve even for a frontend-only start.
call "%~dp0create_env.bat"

docker volume create crew_config
docker volume create crew_pgdata
docker compose --env-file ./../.env --env-file ./../.signing.env -f ./../docker-compose.yaml up frontend
pause
