"""Background process: issues and revokes per-execution temporary MinIO
credentials, and sweeps expired ones.

This is actually started as `python manage.py run_storage_credential_issuer &`
in `src/django_app/entrypoint.sh`, backgrounded alongside the existing
`listen_redis`/`cache_redis` commands.

One event loop, three concurrent tasks (request consumer, result listener,
TTL sweep) plus a heartbeat -- not three separate commands: none of them
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

        tasks = [
            asyncio.create_task(request_consumer.run_forever()),
            asyncio.create_task(result_listener.run_forever()),
            asyncio.create_task(heartbeat.run_forever()),
            asyncio.create_task(self._ttl_loop(ttl_service)),
        ]

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

        logger.info("storage_credential_issuer started")
        await stop_event.wait()
        logger.info("storage_credential_issuer received stop signal, shutting down")

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis_client.aclose()
        await stream_client.close()

    async def _ttl_loop(self, ttl_service: TtlReconciliationService) -> None:
        while True:
            try:
                await ttl_service.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("TTL reconciliation sweep failed: {}", error)
            await asyncio.sleep(TTL_RECONCILIATION_INTERVAL_SECONDS)
