from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from loguru import logger
from tables.models.session_models import Session
from tables.services.session_manager_service import SessionManagerService


def _stop_session_after_commit(session_id) -> None:
    """Call `SessionManagerService.stop_session` for `session_id`, logging rather than raising on failure."""
    try:
        SessionManagerService().stop_session(session_id=session_id)
        logger.info(f"Successfully executed stop_session for Session ID: {session_id}")
    except Exception as e:
        logger.error(f"Error stopping session {session_id} during deletion: {e}", exc_info=True)


@receiver(pre_delete, sender=Session)
def session_pre_delete_handler(sender, instance, **kwargs):
    """Schedule `stop_session` to run after the deleting transaction commits, whether the Session is deleted directly or via cascade (e.g. its parent Graph being deleted)."""
    session_id = instance.pk
    logger.info(f"Triggered pre_delete signal for Session ID: {session_id}")
    transaction.on_commit(lambda: _stop_session_after_commit(session_id))
