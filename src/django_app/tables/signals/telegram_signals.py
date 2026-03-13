from loguru import logger
from django.db.models.signals import post_save
from django.dispatch import receiver

from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.models.graph_models import TelegramTriggerNode


@receiver(post_save, sender=TelegramTriggerNode)
def telegram_trigger_post_save_handler(sender, instance: TelegramTriggerNode, **kwargs):
    id_ = instance.pk
    logger.info(f"Triggered post_save signal for TelegramTriggerNode ID: {id_}")

    try:
        TelegramTriggerService().register_telegram_trigger(
            telegram_trigger_instance=instance
        )
        logger.info(
            f"Successfully registered telegram trigger for TelegramTriggerNode : {id_}"
        )

    except Exception:
        logger.exception("Error registering telegram bot {id_}", id_=id_)
