"""Background process: issues and revokes per-execution temporary MinIO
credentials, and sweeps expired ones.

This is the entrypoint for the dedicated `storage-credential-issuer` service
in `src/docker-compose.yaml` -- same image as `django_app`, its own
`command:`, supervised directly by Docker (`restart: unless-stopped`), not a
backgrounded process inside the `django_app` container.

One event loop, four concurrent tasks (request consumer, result listener,
TTL sweep, heartbeat) -- not four separate commands: none of them
compete for a distinct resource or have a different SLA from each other.
"""

import asyncio
import signal

import redis.asyncio as aioredis
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from src.shared.redis_streams import RedisStreamClient

from storage_credentials.constants import TTL_RECONCILIATION_INTERVAL_SECONDS
from storage_credentials.redis.heartbeat import IssuerHeartbeat
from storage_credentials.redis.request_consumer import StorageCredentialRequestConsumer
from storage_credentials.redis.result_listener import StorageCredentialResultListener
from storage_credentials.services.temporary_credential_service import (
    TemporaryCredentialService,
)
from storage_credentials.services.ttl_reconciliation_service import (
    TtlReconciliationService,
)


class Command(BaseCommand):
    help = "Background issuer/revoker of per-execution temporary MinIO credentials."

    def handle(self, *args, **options):
        asyncio.run(self._main())

    async def _main(self) -> None:
        redis_client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
        )
        stream_client = RedisStreamClient(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
        )
        await stream_client.connect()

        credential_service = TemporaryCredentialService(
            host=settings.STORAGE_ENDPOINT, bucket=settings.STORAGE_BUCKET_NAME
        )
        request_consumer = StorageCredentialRequestConsumer(
            stream_client=stream_client,
            redis_client=redis_client,
            credential_service=credential_service,
        )
        result_listener = StorageCredentialResultListener(
            redis_client=redis_client, credential_service=credential_service
        )
        heartbeat = IssuerHeartbeat(redis_client=redis_client)
        ttl_service = TtlReconciliationService(host=settings.STORAGE_ENDPOINT)

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

        logger.info("storage_credential_issuer started")
        try:
            # TaskGroup supervises all four worker tasks: if any of them
            # raises, the group cancels the rest and re-raises, so
            # `_main()` (and therefore the process, via asyncio.run() in
            # handle()) exits non-zero -- Docker's `restart: unless-stopped`
            # then restarts the whole issuer rather than silently running
            # with one dead task and a heartbeat that stays green.
            # `_wait_for_stop()` is the deliberate-shutdown counterpart: it
            # returns normally (not an exception) once `stop_event` is set
            # and cancels the four worker tasks itself, so a SIGTERM/SIGINT
            # lets the group exit cleanly instead of being treated as a
            # task failure.
            async with asyncio.TaskGroup() as task_group:
                worker_tasks = [
                    task_group.create_task(request_consumer.run_forever()),
                    task_group.create_task(result_listener.run_forever()),
                    task_group.create_task(heartbeat.run_forever()),
                    task_group.create_task(self._ttl_loop(ttl_service)),
                ]
                task_group.create_task(self._wait_for_stop(stop_event, worker_tasks))
        finally:
            logger.info("storage_credential_issuer shutting down")
            await redis_client.aclose()
            await stream_client.close()

    async def _wait_for_stop(
        self, stop_event: asyncio.Event, worker_tasks: list[asyncio.Task]
    ) -> None:
        await stop_event.wait()
        logger.info("storage_credential_issuer received stop signal, shutting down")
        for task in worker_tasks:
            task.cancel()

    async def _ttl_loop(self, ttl_service: TtlReconciliationService) -> None:
        while True:
            try:
                await ttl_service.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("TTL reconciliation sweep failed: {}", error)
            await asyncio.sleep(TTL_RECONCILIATION_INTERVAL_SECONDS)
