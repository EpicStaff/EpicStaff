from typing import Never

from settings import settings
from common.utils import hash_dict
from domain.models import CancelRequest
from infrastructure.task_register import task_register
from loguru import logger
from presentation.handlers import AbstractHandler


class CancelHandler(AbstractHandler[CancelRequest, Never]):
    consumer_channel = settings.CANCEL_REQUEST_CHANNEL
    request_class = CancelRequest

    async def handle(self, request: CancelRequest) -> None:
        key = hash_dict(request.target_request)
        result = task_register.cancel(key)
        if result:
            logger.info("Requested cancellation for request {}", request.target_request)
        else:
            logger.info(
                "No running task for request {}, marked pending-cancel", request.target_request
            )
        return None
