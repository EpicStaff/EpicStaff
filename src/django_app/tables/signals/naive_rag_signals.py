from django.db.models.signals import post_save
from django.dispatch import receiver
from loguru import logger
from tables.services.knowledge_services.naive_rag_service import NaiveRagService


@receiver(post_save, sender="tables.NaiveRag")
def auto_initialize_document_configs(sender, instance, created, **kwargs):
    """
    Auto-initialize document configs when NaiveRag is created.

    Business Logic:
    - Runs ONLY on RAG creation
    - Creates default configs for ALL documents in the collection
    - One-time operation during NaiveRag creation
    """
    if created:
        try:
            configs_created = NaiveRagService.init_document_configs(
                naive_rag_id=instance.naive_rag_id
            )

            logger.info(
                f"[Signal] Auto-initialized {len(configs_created)} document configs "
                f"for NaiveRag {instance.naive_rag_id}"
            )

        except Exception as e:
            logger.error(
                f"[Signal] Failed to auto-initialize document configs for "
                f"NaiveRag {instance.naive_rag_id}: {e!s}"
            )
