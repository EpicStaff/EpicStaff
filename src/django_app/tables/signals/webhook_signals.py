from loguru import logger
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.webhook_models import NgrokWebhookConfig


@receiver(post_save, sender=NgrokWebhookConfig)
def ngrok_webhook_config_post_save_handler(
    sender, instance: NgrokWebhookConfig, **kwargs
):
    id_ = instance.pk
    logger.info(f"Triggered post_save signal for NgrokWebhookConfig ID: {id_}")

    try:
        registered = WebhookTriggerService().register_webhooks()
        if registered:
            logger.info(f"Successfully registered webhooks")
        else:
            logger.error("Register signal was sent but not delivered")
    except Exception:
        logger.exception("Error registering telegram bot {id_}", id_=id_)


@receiver(post_delete, sender=NgrokWebhookConfig)
def ngrok_webhook_config_post_delete_handler(
    sender, instance: NgrokWebhookConfig, **kwargs
):
    id_ = instance.pk
    logger.info(f"Triggered post_delete signal for NgrokWebhookConfig ID: {id_}")

    try:
        registered = WebhookTriggerService().register_webhooks()
        if registered:
            logger.info(f"Successfully registered webhooks")
        else:
            logger.error("Register signal was sent but not delivered")
    except Exception:
        logger.exception("Error registering webhooks")
