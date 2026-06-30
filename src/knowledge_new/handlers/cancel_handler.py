from typing import Never

from handlers import AbstractHandler
from models import CancelRequest
from settings import settings
from task_register import task_register
from utils import hash_dict


class CancelHandler(AbstractHandler[CancelRequest, Never]):
    consumer_channel = settings.CANCEL_REQUEST_CHANNEL
    request_class = CancelRequest

    async def handle(self, request: CancelRequest) -> None:
        key = hash_dict(request.target_request)
        task_register.cancel(key)
        return None
