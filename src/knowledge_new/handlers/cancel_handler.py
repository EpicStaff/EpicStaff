from typing import Never

from loguru import logger

from handlers import AbstractHandler
from models import CancelRequest
from services.task_register import task_register
from settings import settings
from utils import hash_dict


class CancelHandler(AbstractHandler[CancelRequest, Never]):
    consumer_channel = settings.CANCEL_REQUEST_CHANNEL
    request_class = CancelRequest

    async def handle(self, request: CancelRequest) -> None:
        key = hash_dict(request.target_request)
        result = task_register.cancel(key)
        if result:
            logger.info("Requested cancellation for request {}", request.target_request)
        else:
            logger.info("No running task for request {}, marked pending-cancel", request.target_request)
        return None
