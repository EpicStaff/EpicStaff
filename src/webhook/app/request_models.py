from pydantic import BaseModel


class WebhookEventData(BaseModel):
    path: str
    payload: dict