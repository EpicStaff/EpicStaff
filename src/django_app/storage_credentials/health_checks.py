"""Custom `django-health-check` backend exposing the storage-credential
issuer's liveness through the already-mounted `/ht/` endpoint.
"""

import redis
from django.conf import settings
from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceUnavailable

from storage_credentials.redis.keys import ISSUER_HEARTBEAT_KEY


class StorageCredentialIssuerHealthCheck(BaseHealthCheckBackend):
    # Non-critical: the issuer now runs as its own `storage-credential-issuer`
    # Docker service (see docker-compose.yaml), not inside django_app. A dead
    # issuer must not fail django_app's own `/ht/` health check and take the
    # API down with it.
    critical_service = False

    def check_status(self):
        try:
            with redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
            ) as client:
                exists = client.exists(ISSUER_HEARTBEAT_KEY)
        except redis.RedisError as error:
            raise ServiceUnavailable(
                f"Could not reach Redis to check issuer heartbeat: {error}"
            ) from error

        if not exists:
            raise ServiceUnavailable(
                "storage_credential_issuer heartbeat is missing or expired -- "
                "the background credential issuer/revoker process appears "
                "to be down."
            )

    def identifier(self):
        return self.__class__.__name__
