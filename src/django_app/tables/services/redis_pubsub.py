import contextlib
import json
import os
import time

import redis
from django.conf import settings
from django.db import close_old_connections, reset_queries, transaction
from django.utils import timezone
from src.shared.models import (
    CodeResultData,
    StorageMutationEvent,
    WebhookEventData,
)
from src.shared.redis_keys import (
    SESSION_STATUS_CHANNEL_PATTERN,
    session_final_variables_key,
)
from tables.models import (
    Session,
    SessionStorageFile,
    StorageFile,
)
from tables.services.persistent_variables_service import PersistentVariablesService
from tables.services.run_python_code_service import RunPythonCodeService
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.services.session_token_usage import SessionTokenUsageCounter
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.utils.memory_trim import start_periodic_malloc_trim
from utils.logger import logger


class RedisPubSub:
    def __init__(self):
        self.handlers = {}
        self.pattern_handlers = {}
        self.redis_client = self._create_redis_client()
        self.pubsub = self.redis_client.pubsub()
        self.persistent_variables_service = PersistentVariablesService()

    @staticmethod
    def _create_redis_client() -> redis.Redis:
        logger.debug(f"Redis host: {settings.REDIS_HOST}")
        logger.debug(f"Redis port: {settings.REDIS_PORT}")
        return redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            username=settings.REDIS_USER,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
        )

    def _reconnect(self):
        with contextlib.suppress(Exception):
            self.pubsub.close()
        with contextlib.suppress(Exception):
            self.redis_client.close()
        self.redis_client = self._create_redis_client()
        self.pubsub = self.redis_client.pubsub()

    def subscribe_to_channels(self):
        # Called again after every reconnect: the new pubsub starts with no subscriptions.
        if self.handlers:
            self.pubsub.subscribe(**self.handlers)
        if self.pattern_handlers:
            self.pubsub.psubscribe(**self.pattern_handlers)

    def set_handler(self, message_channel: str, handler: callable):
        if message_channel:
            self.handlers[message_channel] = handler
            logger.success(f"Set handler for {message_channel}")

    def set_pattern_handler(self, channel_pattern: str, handler: callable):
        """Register a handler for every channel matching a glob-style pattern.

        The pattern must not match a channel registered with ``set_handler``:
        Redis would deliver a message on it twice, once as ``message`` and once
        as ``pmessage``.
        """
        self.pattern_handlers[channel_pattern] = handler
        logger.success("Set handler for pattern {}", channel_pattern)

    def session_status_handler(self, message: dict):
        try:
            logger.debug("Received message from session_status_handler: {}", message)
            data = json.loads(message["data"])
            close_old_connections()
            with transaction.atomic():
                # Locked so the token total read below cannot interleave with
                # GraphMessageStore storing it: whichever runs second stores the full one.
                # NO KEY UPDATE: it does not wait for the KEY SHARE locks of message inserts.
                session = Session.objects.select_for_update(no_key=True).get(id=data["session_id"])
                if data["status"] == Session.SessionStatus.EXPIRED and session.status in [
                    Session.SessionStatus.END,
                    Session.SessionStatus.ERROR,
                ]:
                    logger.warning(
                        f"Unable change status from {session.status} to {data['status']}"
                    )
                    return

                status_data = data.get("status_data", {})
                final_variables = None
                if data["status"] == Session.SessionStatus.END:
                    final_variables = self._read_session_final_variables(data["session_id"])
                    if final_variables is not None:
                        status_data["variables"] = final_variables
                status_data["total_token_usage"] = SessionTokenUsageCounter(self.redis_client).read(
                    data["session_id"]
                )
                updated_rows = Session.objects.filter(pk=session.pk).update(
                    status=data["status"],
                    status_data=status_data,
                    token_usage=status_data["total_token_usage"],
                    finished_at=session.finished_at
                    or (
                        timezone.now()
                        if data["status"]
                        in [
                            Session.SessionStatus.END,
                            Session.SessionStatus.ERROR,
                            Session.SessionStatus.EXPIRED,
                            Session.SessionStatus.STOP,
                        ]
                        else None
                    ),
                )
                if updated_rows == 0:
                    logger.warning(
                        f"Session {session.pk} was deleted concurrently, skipping status update"
                    )
                    return

            # After the commit: the row lock is released, so these steps do not hold
            # back GraphMessageStore, and a failure in them cannot undo the status.
            if data["status"] in [
                Session.SessionStatus.END,
                Session.SessionStatus.ERROR,
            ]:
                self._persist_finished_session(session, final_variables)

        except Exception as e:
            logger.error(f"Error handling session_status message: {e}")

    def _persist_finished_session(self, session: Session, final_variables: dict | None) -> None:
        # Each step is atomic on its own and logged on failure: one failing must not
        # skip the other.
        try:
            with transaction.atomic():
                self.persistent_variables_service.persist_session_results(
                    session=session,
                    final_variables=final_variables,
                )
        except Exception:
            logger.exception("Could not persist the results of session {}", session.pk)
        try:
            with transaction.atomic():
                self._save_session_storage_files(session=session)
        except Exception:
            logger.exception("Could not link the storage files of session {}", session.pk)

    def _read_session_final_variables(self, session_id: int) -> dict | None:
        # Not deleted after reading: the key expires on its own, so a redelivered
        # `end` status and the SSE views still find it.
        raw_variables = self.redis_client.get(session_final_variables_key(session_id))
        if raw_variables is None:
            logger.warning("No final variables stored for session {}", session_id)
            return None
        return json.loads(raw_variables)

    def code_results_handler(self, message: dict):
        try:
            logger.debug("Received message from code_result_handler: {}", message)
            result = CodeResultData.model_validate_json(message["data"])
            close_old_connections()
            if not RunPythonCodeService().save_execution_result(result):
                logger.debug(f"No pending execution for {result.execution_id}, skipping")
        except Exception as e:
            logger.error(f"Error handling code_results message: {e}")

    def storage_mutations_handler(self, message: dict):
        try:
            logger.debug("Received storage mutation event: {}", message)
            data = json.loads(message["data"])
            event = StorageMutationEvent.model_validate(data)

            org_prefix = event.org_prefix

            try:
                org_id = int(org_prefix.split("_", 1)[1])
            except (IndexError, ValueError):
                logger.error(f"Invalid org_prefix format: {org_prefix}")
                return

            close_old_connections()

            from tables.services.storage_service.db_sync import StorageFileSync
            from tables.services.storage_service.quota import is_over_quota

            for mutation in event.mutations:
                rel_path = mutation.path

                if rel_path and rel_path.startswith(org_prefix + "/"):
                    rel_path = rel_path[len(org_prefix) + 1 :]

                # One bad mutation must not drop the rest of the batch or the bookkeeping below.
                try:
                    if mutation.op == "write":
                        self._record_external_write(org_id, rel_path)
                    elif mutation.op == "delete":
                        StorageFileSync.on_delete(org_id, rel_path)
                except Exception:
                    logger.exception(
                        "Could not sync storage {} of {} in org {}", mutation.op, rel_path, org_id
                    )

            if event.session_id is not None:
                redis_key = f"session:{event.session_id}:storage_mutations"

                for mutation in event.mutations:
                    rel_path = mutation.path

                    if rel_path and rel_path.startswith(org_prefix + "/"):
                        rel_path = rel_path[len(org_prefix) + 1 :]

                    entry = f"{org_id}:{rel_path}"

                    if mutation.op == "write":
                        self.redis_client.sadd(redis_key, entry)
                    elif mutation.op == "delete":
                        self.redis_client.srem(redis_key, entry)

                self.redis_client.expire(redis_key, 7200)

            # Agent writes are already stored, so they cannot be rejected; flag them.
            if any(mutation.op == "write" for mutation in event.mutations) and is_over_quota(
                org_id
            ):
                logger.warning(
                    "Org {} is over its storage quota after agent writes (execution {})",
                    org_id,
                    event.execution_id,
                )

        except Exception as e:
            logger.error(f"Error handling storage_mutations message: {e}")

    @staticmethod
    def _record_external_write(org_id: int, rel_path: str) -> None:
        """Record an agent write at its stored size; if the store can't be asked, without a size."""
        from tables.services.storage_service import get_storage_manager
        from tables.services.storage_service.db_sync import StorageFileSync

        try:
            get_storage_manager().record_external_write(org_id, rel_path)
        except FileNotFoundError:
            logger.warning(
                "Skipping storage write of {} in org {}: no such object", rel_path, org_id
            )
        except Exception:
            logger.exception(
                "Could not read the stored size of {} in org {}; recording it without one",
                rel_path,
                org_id,
            )
            StorageFileSync.on_upload(org_id, rel_path)

    def webhook_events_handler(self, message: dict):
        try:
            logger.debug("Received webhook event: {}", message)
            data = WebhookEventData.model_validate_json(message["data"])
        except Exception as e:
            logger.error(f"Error handling webhook_events_handler message: {e}")
            return

        path = data.path.rstrip("/")
        close_old_connections()

        try:
            WebhookTriggerService().handle_webhook_trigger(
                path=path,
                payload=data.payload,
                config_id=data.config_id,
            )
        except Exception:
            logger.exception(f"Error in generic webhook_trigger handling for path={path}")

        try:
            TelegramTriggerService().handle_telegram_trigger(
                path=path,
                payload=data.payload,
                config_id=data.config_id,
            )
        except Exception:
            logger.exception(f"Error in telegram_trigger handling for path={path}")

    def request_webhook_update_handler(self, message: dict):
        try:
            logger.debug("Received request to update webhook")
            close_old_connections()
            registered = WebhookTriggerService().register_webhooks()
            if not registered:
                raise ValueError("0 services listened for registration")
        except Exception as e:
            logger.error(f"Error updating webhook with current webhook configurations {e}")

    def _save_session_storage_files(self, session: Session):
        try:
            redis_key = f"session:{session.id}:storage_mutations"
            members = self.redis_client.smembers(redis_key)

            if not members:
                return

            file_refs = []

            for member in members:
                try:
                    member_str = member.decode() if isinstance(member, bytes) else member
                    org_id_str, path = member_str.split(":", 1)
                    org_id = int(org_id_str)
                    storage_file = StorageFile.objects.filter(org_id=org_id, path=path).first()

                    if storage_file:
                        file_refs.append(
                            SessionStorageFile(session=session, storage_file=storage_file)
                        )

                except Exception as e:
                    logger.warning(f"Skipping malformed session storage entry '{member}': {e}")

            if file_refs:
                SessionStorageFile.objects.bulk_create(file_refs, ignore_conflicts=True)

            self.redis_client.delete(redis_key)

        except Exception as e:
            logger.error(f"Error saving session storage files: {e}")

    def listen_for_messages(self):
        try:
            self._dispatch_next_message()
        finally:
            # With DEBUG on, Django keeps every executed query, parameters included, in
            # connection.queries_log. Only the HTTP request cycle clears it, and the
            # workers have none, so a 300 KB insert would stay alive forever. Reset after
            # every read: get_message() runs the registered handlers itself.
            reset_queries()

    def _dispatch_next_message(self):
        message = None
        try:
            # Calls the handler registered for the message's channel or pattern, and
            # then returns None.
            message = self.pubsub.get_message(ignore_subscribe_messages=True, timeout=0.001)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.error(f"Error while listening for Redis messages: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error while listening for Redis messages: {e}")

        if message:
            channel = message.get("channel", "")
            handler = self.handlers.get(channel)
            if handler:
                try:
                    handler(message)
                except Exception as e:
                    logger.error(f"Error in handler for channel {channel}: {e}")
            else:
                logger.warning(f"No handler found for channel: {channel}")

    def _run_with_reconnect(self, label: str, inner_loop):
        while True:
            try:
                self.subscribe_to_channels()
                inner_loop()
            except Exception as e:
                logger.error(f"Redis {label} disconnected, reconnecting in 1s: {e}")
                time.sleep(1)
                self._reconnect()

    def listen_for_redis_messages_worker(self):
        logger.info(f"Start worker {os.getpid()} listening for Redis messages...")
        start_periodic_malloc_trim()
        self.set_pattern_handler(SESSION_STATUS_CHANNEL_PATTERN, self.session_status_handler)
        self.set_handler(settings.CODE_RESULT_CHANNEL, self.code_results_handler)
        self.set_handler(settings.WEBHOOK_MESSAGE_CHANNEL, self.webhook_events_handler)
        self.set_handler(
            settings.REQUEST_WEBHOOK_UPDATE_CHANNEL, self.request_webhook_update_handler
        )
        self.set_handler(settings.SCHEDULE_CHANNEL, self.schedule_channel_handler)
        self.set_handler(settings.STORAGE_MUTATION_CHANNEL, self.storage_mutations_handler)

        def inner_loop():
            while True:
                self.listen_for_messages()

        self._run_with_reconnect("listener", inner_loop)

    def schedule_channel_handler(self, message: dict):
        """Router for schedule_channel messages coming from Manager.

        Channel direction rules:
          - 'node_update' is Django → Manager; we see the echo of our own
            post_save publish and skip it silently here.
          - 'run_session' and 'deactivate' are Manager → Django and are the
            only actions consumed on this side.

        Supported actions:
          - 'run_session' → start a session via ScheduleTriggerService
            (guard checks + run_session + increment_runs — all atomic)
          - 'deactivate'  → set is_active=False (published by Manager after a
            once-mode fire or when APScheduler auto-removes a job, e.g. when
            end_date is reached)

        Input:
            message["data"] — JSON string:
            {"action": "run_session"|"deactivate", "node_id": <int>}
        """
        try:
            logger.debug("[SchedulePubSub] Received: {}", message)
            data = json.loads(message["data"])
            action = data.get("action")

            if action == "node_update":
                return

            node_id = data.get("node_id")
            if not node_id:
                logger.warning("[SchedulePubSub] node_id missing in message")
                return

            if action == "run_session":
                self._handle_schedule_run_session(node_id)
            elif action == "deactivate":
                self._handle_schedule_deactivate(node_id)
            else:
                logger.warning(f"[SchedulePubSub] Unknown action: {action}")
        except Exception as e:
            logger.error(f"[SchedulePubSub] Error handling message: {e}")

    def _handle_schedule_run_session(self, node_id: int):
        """
        Starts a graph session via ScheduleTriggerService.

        All business logic is encapsulated in the service:
          - guard checks (start_date, end_date, max_runs)
          - select_for_update(skip_locked=True) for race condition protection
          - run_session()
          - atomic current_runs increment via F()

        Input:  node_id — PK of the ScheduleTriggerNode
        """
        try:
            close_old_connections()
            ScheduleTriggerService().handle_schedule_trigger(node_id)
            logger.info(f"[SchedulePubSub] run_session completed for node {node_id}")
        except Exception as e:
            logger.error(f"[SchedulePubSub] Error in run_session for node {node_id}: {e}")

    def _handle_schedule_deactivate(self, node_id: int):
        try:
            close_old_connections()
            ScheduleTriggerService().deactivate_node(node_id)
        except Exception as e:
            logger.error(f"[SchedulePubSub] Error deactivating node {node_id}: {e}")
