import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
from django.db import close_old_connections
from django.utils import timezone
from tables.models import Session, SessionCallback
from tables.services.secrets import SecretDecryptionError, secret_encryption
from tables.services.session_callbacks.service import SessionCallbackService
from tables.services.session_callbacks.signing import (
    SESSION_ID_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    canonical_body,
    sign,
)
from utils.logger import logger

# Wait between attempts, indexed by the number of attempts already made.
RETRY_DELAYS = [
    timedelta(seconds=1),
    timedelta(seconds=5),
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
] + [timedelta(hours=1)] * 24
# The `graph_end` message is persisted by another process; give it this many
# one-second waits before an `end` status is sent with a null result.
MAX_RESULT_WAIT_ATTEMPTS = 3
RESULT_WAIT = timedelta(seconds=1)
BATCH_SIZE = 50
# Rows of one batch are POSTed in parallel: each send waits on the receiver's
# transaction, so serial sends cap throughput at roughly 1 / receive latency.
SEND_CONCURRENCY = 16
REQUEST_TIMEOUT_SECONDS = 10.0


class SessionCallbackSender:
    """Deliver pending session callbacks with retries.

    One instance per process; `transport` lets tests capture requests without a
    network.
    """

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            transport=transport,
            timeout=REQUEST_TIMEOUT_SECONDS,
            limits=httpx.Limits(
                max_connections=SEND_CONCURRENCY, max_keepalive_connections=SEND_CONCURRENCY
            ),
        )
        self._callback_service = SessionCallbackService()

    def send_due(self, now: datetime) -> int:
        """Settle stale registered rows, then attempt every pending callback that is due.

        Database work stays on the calling thread; only the HTTP POSTs run in the
        pool, so worker threads never open a database connection.

        Rows are claimed without a lock or lease. That relies on exactly one sender
        process, which holds while compose runs a single `django_app` container
        (`container_name: django_app`). Running replicas would need the selection
        below to use `select_for_update(skip_locked=True)` inside a transaction.

        Returns:
            The number of rows attempted in this pass.
        """
        self._callback_service.reap_stale(now)
        due = list(
            SessionCallback.objects.filter(
                status=SessionCallback.Status.PENDING, next_attempt_at__lte=now
            ).order_by("next_attempt_at")[:BATCH_SIZE]
        )
        ready = []
        secrets = []
        for callback in due:
            try:
                secret = secret_encryption.decrypt(encryptedtext=callback.encrypted_secret)
                if self._ensure_result(callback, timezone.now()):
                    ready.append(callback)
                    secrets.append(secret)
            except SecretDecryptionError as exc:
                # A retry cannot succeed: the key that sealed it (SECRET_KEY) is gone.
                self._mark_failed(
                    callback,
                    callback.attempts,
                    f"Callback secret cannot be decrypted: {exc}",
                    timezone.now(),
                )
            except Exception as exc:  # one bad row must not stall the rows behind it
                self._record_crash(callback, exc)
        with ThreadPoolExecutor(max_workers=SEND_CONCURRENCY) as executor:
            outcomes = list(executor.map(self._post, ready, secrets))
        for callback, (attempt_time, error) in zip(ready, outcomes, strict=True):
            try:
                self._record_outcome(callback, error, attempt_time)
            except Exception as exc:  # one bad row must not stall the rows behind it
                self._record_crash(callback, exc)
        return len(due)

    def _post(self, callback: SessionCallback, secret: str) -> tuple[datetime, str]:
        """Sign and POST one callback. Runs in a pool thread: no database access, never raises.

        Returns:
            The attempt time and an error string, empty on success.
        """
        attempt_time = timezone.now()
        try:
            body = canonical_body(callback.payload)
            timestamp = str(int(attempt_time.timestamp()))
            headers = {
                "Content-Type": "application/json",
                SESSION_ID_HEADER: str(callback.session_id),
                TIMESTAMP_HEADER: timestamp,
                SIGNATURE_HEADER: sign(secret, timestamp, body),
            }
            response = self._client.post(callback.url, content=body.encode(), headers=headers)
            return attempt_time, "" if response.is_success else f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            return attempt_time, f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # one bad row must not stall the rows behind it
            logger.error("Session {} callback attempt crashed: {}", callback.session_id, exc)
            return attempt_time, f"{type(exc).__name__}: {exc}"

    def _record_outcome(
        self, callback: SessionCallback, error: str, attempt_time: datetime
    ) -> None:
        if not error:
            SessionCallback.objects.filter(pk=callback.pk).update(
                status=SessionCallback.Status.DELIVERED,
                encrypted_secret="",
                last_error="",
                updated_at=attempt_time,
            )
            logger.info("Session {} callback delivered", callback.session_id)
            return
        self._record_failure(callback, error, attempt_time)

    def _record_crash(self, callback: SessionCallback, exc: Exception) -> None:
        logger.error("Session {} callback attempt crashed: {}", callback.session_id, exc)
        self._record_failure(callback, f"{type(exc).__name__}: {exc}", timezone.now())

    def _record_failure(self, callback: SessionCallback, error: str, when: datetime) -> None:
        attempts = callback.attempts + 1
        if attempts > len(RETRY_DELAYS):
            self._mark_failed(callback, attempts, error, when)
            return
        SessionCallback.objects.filter(pk=callback.pk).update(
            attempts=attempts,
            next_attempt_at=when + RETRY_DELAYS[attempts - 1],
            last_error=error,
            updated_at=when,
        )
        logger.warning(
            "Session {} callback attempt {} failed: {}", callback.session_id, attempts, error
        )

    @staticmethod
    def _mark_failed(callback: SessionCallback, attempts: int, error: str, when: datetime) -> None:
        SessionCallback.objects.filter(pk=callback.pk).update(
            status=SessionCallback.Status.FAILED,
            encrypted_secret="",
            attempts=attempts,
            last_error=error,
            updated_at=when,
        )
        logger.error("Session {} callback failed for good: {}", callback.session_id, error)

    def _ensure_result(self, callback: SessionCallback, now: datetime) -> bool:
        """Fill a missing `end` result from the database; postpone briefly while it is absent.

        `result_waits` is a scratch key in the stored payload, removed before
        sending so the wire payload stays exactly the contract fields.

        Returns:
            True when the callback may be sent now.
        """
        payload = callback.payload
        if (
            payload.get("status") != Session.SessionStatus.END
            or payload.get("end_node_result") is not None
        ):
            return True
        result = self._callback_service.end_node_result(callback.session_id)
        waited = int(payload.get("result_waits", 0))
        if result is None and waited < MAX_RESULT_WAIT_ATTEMPTS:
            payload["result_waits"] = waited + 1
            SessionCallback.objects.filter(pk=callback.pk).update(
                payload=payload, next_attempt_at=now + RESULT_WAIT, updated_at=now
            )
            return False
        payload.pop("result_waits", None)
        payload["end_node_result"] = result
        callback.payload = payload
        SessionCallback.objects.filter(pk=callback.pk).update(payload=payload, updated_at=now)
        return True

    def run_forever(self, interval_seconds: float = 1.0) -> None:
        """Poll until the process is stopped. Used by the management command."""
        logger.info("Session callback sender started")
        while True:
            close_old_connections()
            attempted = 0
            try:
                attempted = self.send_due(timezone.now())
            except Exception as exc:  # the loop must outlive one bad row or a DB blip
                logger.error("Session callback sender pass failed: {}", exc)
            if attempted < BATCH_SIZE:  # a full batch means more rows are likely due now
                time.sleep(interval_seconds)
