import json
import os
import time
from collections import defaultdict, deque
from typing import Type
from uuid import uuid4

import redis
from django.db import close_old_connections, IntegrityError, models, transaction
from loguru import logger

from django_app.settings import (
    CODE_RESULT_CHANNEL,
    GRAPH_MESSAGE_UPDATE_CHANNEL,
    GRAPH_MESSAGES_CHANNEL,
    SESSION_STATUS_CHANNEL,
    STORAGE_MUTATION_CHANNEL,
    TELEGRAM_TRIGGER_PREFIX,
    WEBHOOK_MESSAGE_CHANNEL,
    REQUEST_WEBHOOK_UPDATE_CHANNEL,
)
from tables.models import (
    GraphOrganization,
    GraphSessionMessage,
    PythonCodeResult,
    Session,
    SessionStorageFile,
    StorageFile,
)
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService
from src.shared.models import (
    CodeResultData,
    GraphSessionMessageData,
    StorageMutationEvent,
    WebhookEventData,
)


class RedisPubSub:
    def __init__(self):
        redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_password = os.getenv("REDIS_PASSWORD")
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
        )
        self.pubsub = self.redis_client.pubsub()

        self.handlers = {}
        self.buffers = {GRAPH_MESSAGES_CHANNEL: deque(maxlen=1000)}

        logger.debug(f"Redis host: {redis_host}")
        logger.debug(f"Redis port: {redis_port}")

    def subscribe_to_channels(self):
        self.pubsub.subscribe(**self.handlers)

    def set_handler(self, message_channel: str, handler: callable):
        if message_channel:
            self.handlers[message_channel] = handler
            logger.success(f"Set handler for {message_channel}")

    def session_status_handler(self, message: dict):
        try:
            logger.debug(f"Received message from session_status_handler: {message}")
            data = json.loads(message["data"])
            close_old_connections()
            with transaction.atomic():
                session = Session.objects.get(id=data["session_id"])
                if data[
                    "status"
                ] == Session.SessionStatus.EXPIRED and session.status in [
                    Session.SessionStatus.END,
                    Session.SessionStatus.ERROR,
                ]:
                    logger.warning(
                        f"Unable change status from {session.status} to {data['status']}"
                    )
                else:
                    status_data = data.get("status_data", {})
                    status_data["total_token_usage"] = (
                        self._calculate_total_token_usage(data["session_id"])
                    )
                    session.status = data["status"]
                    session.status_data = status_data
                    session.token_usage = status_data["total_token_usage"]
                    session.save()

                    if session.status in [
                        Session.SessionStatus.END,
                        Session.SessionStatus.ERROR,
                    ]:
                        self._save_organization_variables(session=session, data=data)
                        self._save_session_storage_files(session=session)

        except Exception as e:
            logger.error(f"Error handling session_status message: {e}")

    def code_results_handler(self, message: dict):
        try:
            logger.debug(f"Received message from code_result_handler: {message}")
            data = json.loads(message["data"])
            CodeResultData.model_validate(data)
            close_old_connections()
            PythonCodeResult.objects.create(**data)
        except Exception as e:
            logger.error(f"Error handling code_results message: {e}")

    def storage_mutations_handler(self, message: dict):
        try:
            logger.debug(f"Received storage mutation event: {message}")
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

            for mutation in event.mutations:
                rel_path = mutation.path

                if rel_path and rel_path.startswith(org_prefix + "/"):
                    rel_path = rel_path[len(org_prefix) + 1 :]

                if mutation.op == "write":
                    StorageFileSync.on_upload(org_id, rel_path)
                elif mutation.op == "delete":
                    StorageFileSync.on_delete(org_id, rel_path)

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

        except Exception as e:
            logger.error(f"Error handling storage_mutations message: {e}")

    def webhook_events_handler(self, message: dict):
        try:
            logger.debug(f"Received webhook event: {message}")
            data = WebhookEventData.model_validate_json(message["data"])
            if data.path.startswith(TELEGRAM_TRIGGER_PREFIX):
                TelegramTriggerService().handle_telegram_trigger(
                    url_path=data.path[len(TELEGRAM_TRIGGER_PREFIX) : -1],
                    payload=data.payload,
                    config_id=data.config_id,
                )
            else:
                WebhookTriggerService().handle_webhook_trigger(
                    path=data.path,
                    payload=data.payload,
                    config_id=data.config_id,
                )
        except Exception as e:
            logger.error(f"Error handling webhook_events_handler message: {e}")

    def request_webhook_update_handler(self, message: dict):
        try:
            logger.debug(f"Received request to update webhook")
            registered = WebhookTriggerService().register_webhooks()
            if not registered:
                raise ValueError("0 services listened for registration")
        except Exception as e:
            logger.error(
                f"Error updating webhook with current webhook configurations {e}"
            )

    def _save_organization_variables(self, session: Session, data: dict):
        """
        Save organization and organization_user variables to database.
        Only updates values that exist in the persistent_variables structure.
        """
        try:
            variables = data["status_data"]["variables"]
            if not variables:
                return

            graph_organization = GraphOrganization.objects.filter(
                graph=session.graph
            ).first()
            if graph_organization and graph_organization.persistent_variables:
                if self._update_persistent_values(
                    graph_organization.persistent_variables, variables
                ):
                    graph_organization.save(update_fields=["persistent_variables"])

            if (
                session.graph_user
                and graph_organization.user_variables
                and not session.graph_user.persistent_variables
            ):
                session.graph_user.persistent_variables = (
                    graph_organization.user_variables
                )
                session.graph_user.save()

            if session.graph_user and session.graph_user.persistent_variables:
                if self._update_persistent_values(
                    session.graph_user.persistent_variables, variables
                ):
                    session.graph_user.save(update_fields=["persistent_variables"])

        except Exception as e:
            logger.error(f"Error handling organization variables message: {e}")

    def _save_session_storage_files(self, session: Session):
        try:
            redis_key = f"session:{session.id}:storage_mutations"
            members = self.redis_client.smembers(redis_key)

            if not members:
                return

            file_refs = []

            for member in members:
                try:
                    member_str = (
                        member.decode() if isinstance(member, bytes) else member
                    )
                    org_id_str, path = member_str.split(":", 1)
                    org_id = int(org_id_str)
                    storage_file = StorageFile.objects.filter(
                        org_id=org_id, path=path
                    ).first()

                    if storage_file:
                        file_refs.append(
                            SessionStorageFile(
                                session=session, storage_file=storage_file
                            )
                        )

                except Exception as e:
                    logger.warning(
                        f"Skipping malformed session storage entry '{member}': {e}"
                    )

            if file_refs:
                SessionStorageFile.objects.bulk_create(file_refs, ignore_conflicts=True)

            self.redis_client.delete(redis_key)

        except Exception as e:
            logger.error(f"Error saving session storage files: {e}")

    def _update_persistent_values(self, persistent: dict, incoming: dict) -> bool:
        """
        Recursively update values in persistent dict from incoming dict.
        Only updates keys that already exist in persistent.
        Returns True if any values were updated.
        """
        updated = False

        for key, persistent_value in persistent.items():
            if key not in incoming:
                continue

            incoming_value = incoming[key]

            if isinstance(persistent_value, dict) and isinstance(incoming_value, dict):
                if self._update_persistent_values(persistent_value, incoming_value):
                    updated = True
            elif persistent_value != incoming_value:
                persistent[key] = incoming_value
                updated = True

        return updated

    def _buffer_save(self, data, model: Type[models.Model]):
        try:
            close_old_connections()
            with transaction.atomic():
                created_objects = model.objects.bulk_create(data, ignore_conflicts=True)
                logger.debug(
                    f"{model.__name__} updated with {len(created_objects)}/{len(data)} entities"
                )
        except IntegrityError as e:
            logger.error(f"Failed to save {model.__name__}: {e}")

    def _calculate_total_token_usage(self, session_id):
        pattern = f"graph:message:{session_id}:*"
        cached_keys = self.redis_client.keys(pattern)

        total_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
        }

        for key in cached_keys:
            try:
                data = json.loads(self.redis_client.get(key))
                message_data = data.get("message_data", {})

                if not message_data:
                    return total_usage

                token_usage = None

                output = message_data.get("output")
                if isinstance(output, dict) and "token_usage" in message_data["output"]:
                    token_usage = message_data["output"]["token_usage"]
                elif "token_usage" in message_data:
                    token_usage = message_data["token_usage"]

                if token_usage:
                    total_usage["total_tokens"] += token_usage.get("total_tokens", 0)
                    total_usage["prompt_tokens"] += token_usage.get("prompt_tokens", 0)
                    total_usage["completion_tokens"] += token_usage.get(
                        "completion_tokens", 0
                    )
                    total_usage["successful_requests"] += token_usage.get(
                        "successful_requests", 0
                    )

            except Exception as e:
                logger.error(f"Error parsing cached message for key {key}: {e}")

        return total_usage

    def graph_session_message_handler(self, message: dict):
        try:
            logger.info(f"Received message from graph_message_handler: {message}")
            data = json.loads(message["data"])
            graph_session_message_data = GraphSessionMessageData.model_validate(data)
            message_uuid = graph_session_message_data.uuid
            session_id = graph_session_message_data.session_id
            close_old_connections()
            if not Session.objects.filter(pk=session_id).exists():
                logger.warning(f"Session {session_id} was deleted")
                return

            buffer = self.buffers.setdefault(GRAPH_MESSAGES_CHANNEL, deque(maxlen=1000))

            if any(d.get("uuid") == message_uuid for d in buffer):
                logger.warning("This message already proceeded")
                return

            message_type = graph_session_message_data.message_data.get("message_type")

            # Save in Redis.
            self.redis_client.setex(
                name=f"graph:message:{session_id}:{message_uuid}",
                time=60,
                value=json.dumps(data),
            )

            # Save in buffer.
            buffer.append(
                dict(
                    session_id=session_id,
                    created_at=graph_session_message_data.timestamp,
                    name=graph_session_message_data.name,
                    execution_order=graph_session_message_data.execution_order,
                    message_data=graph_session_message_data.message_data,
                    uuid=message_uuid,
                )
            )

            # Notify SSE about updates.
            self.redis_client.publish(
                GRAPH_MESSAGE_UPDATE_CHANNEL,
                json.dumps({"uuid": str(message_uuid), "session_id": session_id}),
            )

            # After main flow completes, create subgraph sessions from message history.
            if message_type == "graph_end":
                self._flush_buffer()
                self._create_subgraph_sessions(root_session_id=session_id)

        except Exception as e:
            logger.error(f"Error handling graph_session_message: {e}")

    def listen_for_messages(self):
        try:
            message = self.pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.001
            )
            if message:
                channel = message.get("channel", "")
                handler = self.handlers.get(channel)

                if handler:
                    handler(message)
                else:
                    logger.warning(f"No handler found for channel: {channel}")
        except Exception as e:
            logger.error(f"Error while listening for Redis messages: {e}")

    # TODO: listen_for_redis_messages_worker and cache_for_redis_messages_worker
    # can be optimized and combined to one function
    def listen_for_redis_messages_worker(self):
        logger.info(f"Start worker {os.getpid()} listening for Redis messages...")
        self.set_handler(SESSION_STATUS_CHANNEL, self.session_status_handler)
        self.set_handler(CODE_RESULT_CHANNEL, self.code_results_handler)
        self.set_handler(WEBHOOK_MESSAGE_CHANNEL, self.webhook_events_handler)
        self.set_handler(
            REQUEST_WEBHOOK_UPDATE_CHANNEL, self.request_webhook_update_handler
        )
        self.set_handler(STORAGE_MUTATION_CHANNEL, self.storage_mutations_handler)
        self.subscribe_to_channels()

        while True:
            self.listen_for_messages()

    def cache_for_redis_messages_worker(self):
        """Saves to DB a bunch of data"""
        logger.info(f"Start worker {os.getpid()} caching for Redis messages...")
        self.set_handler(GRAPH_MESSAGES_CHANNEL, self.graph_session_message_handler)
        self.subscribe_to_channels()

        start_time = time.time()
        while True:
            try:
                # 1. Listen for new message
                self.listen_for_messages()

                # 2. Bulk save the buffer, clear state
                buffer = self.buffers.get(GRAPH_MESSAGES_CHANNEL)
                if buffer and time.time() - start_time >= 3:
                    self._flush_buffer()
                    start_time = time.time()

            except Exception as e:
                # Catch general exceptions in the listener loop (e.g., Redis errors)
                logger.error(f"Error in main listener loop: {e}")
            except Exception as e:
                logger.error(f"Error while saving graph session messages: {e}")

    def _flush_buffer(self):
        """Flush the graph messages buffer to the database.

        Converts buffered dicts into GraphSessionMessage instances, groups them
        by session_id, and bulk-saves each group. Clears the buffer afterwards.
        """

        buffer = self.buffers.get(GRAPH_MESSAGES_CHANNEL)

        try:
            graph_session_message_list = [
                GraphSessionMessage(**data) for data in list(buffer)
            ]

        except Exception:
            logger.critical("Error creating GraphSessionMessage in database")
            buffer.clear()
            return

        buffer.clear()
        sessions_data = defaultdict(deque)

        for graph_session_message in graph_session_message_list:
            session_id = graph_session_message.session.pk
            if session_id is not None:
                sessions_data[session_id].append(graph_session_message)
            else:
                logger.warning(
                    f"Skipping entity for {GraphSessionMessage.__name__} with missing session_id: {session_id}"
                )

        for session_id, sessions_data_values in sessions_data.items():
            self._buffer_save(data=sessions_data_values, model=GraphSessionMessage)

    def _create_subgraph_sessions(self, root_session_id):
        """Create subgraph sessions after main session completes.

        Scans all messages for the root session, finds subgraph_start/finish
        pairs, creates Session records with proper parent hierarchy, copies
        relevant messages to each subgraph session, and calculates token usage.

        Uses three passes:
          1. Forward pass: create Session records (parents before children).
          2. Copy messages: for each subgraph, copy messages whose
             message_data.subgraph_execution_ids contains that exec_id.
          3. Reverse pass: calculate token usage (children before parents
             so parent can aggregate child usage).

        Args:
            root_session_id: The ID of the completed root session.
        """
        if Session.objects.filter(parent_session_id=root_session_id).exists():
            logger.debug(
                f"Subgraph sessions already exist for root session {root_session_id}"
            )
            return

        try:
            root_session = Session.objects.get(pk=root_session_id)
        except Session.DoesNotExist:
            logger.warning(f"Root session {root_session_id} not found")
            return

        buffer = self.buffers.setdefault(GRAPH_MESSAGES_CHANNEL, deque(maxlen=1000))

        all_messages = list(
            GraphSessionMessage.objects.filter(session_id=root_session_id).order_by(
                "id"
            )
        )

        # look for the start/finish subgraph message_data
        start_msgs = {}
        finish_msgs = {}
        ordered_exec_ids = []

        for msg in all_messages:
            msg_data = msg.message_data or {}
            msg_type = msg_data.get("message_type")
            if msg_type == "subgraph_start":
                exec_id = msg_data.get("subgraph_execution_id")
                if exec_id:
                    start_msgs[exec_id] = msg_data
                    ordered_exec_ids.append(exec_id)
            elif msg_type == "subgraph_finish":
                exec_id = msg_data.get("subgraph_execution_id")
                if exec_id:
                    finish_msgs[exec_id] = msg_data

        if not start_msgs:
            return

        exec_id_to_session_id = {}
        created_sessions = []

        # Create sessions (forward order — parents before children)
        for exec_id in ordered_exec_ids:
            start_data = start_msgs[exec_id]
            finish_data = finish_msgs.get(exec_id, {})

            subgraph_id = start_data.get("subgraph_id")
            subgraph_input = start_data.get("input", {})
            subgraph_output = finish_data.get("output", {})

            # check if parent subgraph exist
            ancestor_exec_ids = start_data.get("subgraph_execution_ids") or []
            if ancestor_exec_ids:
                parent_session_id = exec_id_to_session_id.get(
                    ancestor_exec_ids[0], root_session_id
                )
            else:
                parent_session_id = root_session_id

            if not finish_data:
                status = Session.SessionStatus.ERROR
            else:
                status = Session.SessionStatus.END

            session = Session.objects.create(
                graph_id=subgraph_id,
                status=status,
                parent_session_id=parent_session_id,
                variables=subgraph_output or subgraph_input,
                time_to_live=root_session.time_to_live,
                graph_schema=root_session.graph_schema,
            )

            exec_id_to_session_id[exec_id] = session.pk
            created_sessions.append((exec_id, session, finish_data))

        # Copy messages to each subgraph session via buffer,
        # and keep source messages per exec_id for token calculation.
        exec_id_messages = {}
        for exec_id, session, _ in created_sessions:
            matching = [
                msg
                for msg in all_messages
                if exec_id
                in ((msg.message_data or {}).get("subgraph_execution_ids") or [])
            ]
            exec_id_messages[exec_id] = matching

            copies = [
                dict(
                    session_id=session.pk,
                    created_at=msg.created_at,
                    name=msg.name,
                    execution_order=msg.execution_order,
                    message_data=msg.message_data,
                    uuid=uuid4(),
                )
                for msg in matching
            ]

            if copies:
                buffer.extend(copies)

        # Calculate token usage from source messages already in DB
        # (reverse order — children before parents so parent can aggregate).
        for exec_id, session, finish_data in reversed(created_sessions):
            token_usage = self._calculate_subgraph_token_usage(
                exec_id_messages.get(exec_id, [])
            )

            subgraph_output = finish_data.get("output", {})

            session.token_usage = token_usage
            session.status_data = {
                "total_token_usage": token_usage,
                "variables": subgraph_output,
            }
            session.save()

    @staticmethod
    def _calculate_subgraph_token_usage(messages: list) -> dict:
        """Calculate total token usage from a list of GraphSessionMessage instances.

        Uses the same extraction logic as _calculate_total_token_usage but
        operates on in-memory message objects instead of Redis cache.
        This is needed because subgraph messages are only cached in Redis
        under the root session ID, not under the subgraph session ID.

        Args:
            messages: List of GraphSessionMessage instances to aggregate from.

        Returns:
            Dict with total_tokens, prompt_tokens, completion_tokens,
            successful_requests.
        """
        total_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
        }

        for msg in messages:
            msg_data = msg.message_data or {}
            token_usage = None

            output = msg_data.get("output")
            if isinstance(output, dict) and "token_usage" in output:
                token_usage = msg_data["output"]["token_usage"]
            elif "token_usage" in msg_data:
                token_usage = msg_data["token_usage"]

            if token_usage:
                total_usage["total_tokens"] += token_usage.get("total_tokens", 0)
                total_usage["prompt_tokens"] += token_usage.get("prompt_tokens", 0)
                total_usage["completion_tokens"] += token_usage.get(
                    "completion_tokens", 0
                )
                total_usage["successful_requests"] += token_usage.get(
                    "successful_requests", 0
                )

        return total_usage
