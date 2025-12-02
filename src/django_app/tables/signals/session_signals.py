from loguru import logger
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from tables.models.session_models import Session
from tables.services.session_manager_service import SessionManagerService


@receiver(pre_delete, sender=Session)
def session_pre_delete_handler(sender, instance, **kwargs):
    """
    Handles cleanup tasks before a Session is deleted.
    This signal is triggered during explicit session deletion
    and cascade deletion (e.g., when the parent Graph is deleted).
    """
    session_id = instance.pk
    logger.info(f"Triggered pre_delete signal for Session ID: {session_id}")

    try:
        SessionManagerService().stop_session(session_id=session_id)
        logger.info(f"Successfully executed stop_session for Session ID: {session_id}")

    except Exception as e:
        logger.error(
            f"Error stopping session {session_id} during deletion: {e}", exc_info=True
        )
