import json
import os
import time
from typing import Type
import redis
from collections import deque
from django.db import transaction, IntegrityError, models
from tables.models import GraphSessionMessage
from tables.models import PythonCodeResult
from tables.request_models import CodeResultData, GraphSessionMessageData
from tables.services.session_manager_service import SessionManagerService
from tables.models import Session
from loguru import logger


SESSION_STATUS_CHANNEL = os.environ.get(
    "SESSION_STATUS_CHANNEL", "sessions:session_status"
)
CODE_RESULT_CHANNEL = os.environ.get("CODE_RESULT_CHANNEL", "code_results")
GRAPH_MESSAGES_CHANNEL = os.environ.get("GRAPH_MESSAGES_CHANNEL", "graph:messages")
GRAPH_MESSAGE_UPDATE_CHANNEL = os.environ.get(
    "GRAPH_MESSAGE_UPDATE_CHANNEL", "graph:message:update"
)


class RedisPubSub:

    def __init__(self):
        redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        redis_port = int(os.getenv("REDIS_PORT", 6379))

        self.redis_client = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
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
            with transaction.atomic():
                session = Session.objects.get(id=data["session_id"])
                if data[
                    "status"
                ] == Session.SessionStatus.EXPIRED and session.status in [
                    Session.SessionStatus.END,
                    Session.SessionStatus.ERROR,
                ]:
                    logger.warning(
                        f'Unable change status from {session.status} to {data["status"]}'
                    )
                else:
                    session.status = data["status"]
                    session.status_data = data.get("status_data", {})
                    session.save()
        except Exception as e:
            logger.error(f"Error handling session_status message: {e}")

    def code_results_handler(self, message: dict):
        try:
            logger.debug(f"Received message from code_result_handler: {message}")
            data = json.loads(message["data"])
            CodeResultData.model_validate(data)
            PythonCodeResult.objects.create(**data)
        except Exception as e:
            logger.error(f"Error handling code_results message: {e}")

    def _buffer_save(self, buffer: deque[dict], model: Type[models.Model]):
        try:
            with transaction.atomic():
                objects = [model(**data) for data in list(buffer)]
                created_objects = model.objects.bulk_create(
                    objects, ignore_conflicts=True
                )
                buffer.clear()
                logger.debug(
                    f"{model.__name__} updated with {len(created_objects)}/{len(objects)} entities"
                )
        except IntegrityError as e:
            logger.error(f"Failed to save {model.__name__}: {e}")

    def graph_session_message_handler(self, message: dict):
        try:
            logger.info(f"Received message from graph_message_handler: {message}")
            data = json.loads(message["data"])
            graph_session_message_data = GraphSessionMessageData.model_validate(data)
            message_uuid = graph_session_message_data.uuid
            session_id = graph_session_message_data.session_id

            buffer = self.buffers.setdefault(GRAPH_MESSAGES_CHANNEL, deque(maxlen=1000))

            if any(d.get("uuid") == message_uuid for d in buffer):
                logger.warning("This message already proceeded")
                return

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

    def listen_for_redis_messages_worker(self):
        logger.info(f"Start worker {os.getpid()} listening for Redis messages...")
        self.set_handler(SESSION_STATUS_CHANNEL, self.session_status_handler)
        self.set_handler(CODE_RESULT_CHANNEL, self.code_results_handler)
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
                    self._buffer_save(buffer=buffer, model=GraphSessionMessage)
                    start_time = time.time()

            except Exception as e:
                logger.error(f"Error while saving graph session messages: {e}")
