"""The wire codec every worker transport shares.

Decoding and encoding live here once, so the in-process queue adapters and the network
adapters cannot drift apart on the wire shape. The application never sees these types:
a transport decodes an ``ExecutionJobMessage`` into a domain ``Job`` on the way in and
encodes the domain result into an ``ExecutionResultMessage`` on the way out.
"""

from common.contracts import ExecutionJobMessage, ExecutionResultMessage, StorageMutationsMessage
from pydantic import ValidationError

from worker.application.ports.job_source import UndecodableJobError
from worker.domain.models import ExecutionResult, Job, StorageMutations

__all__ = ["decode_job", "encode_result"]


def decode_job(message: ExecutionJobMessage) -> Job:
    """Decode the wire message into a domain ``Job`` at the boundary.

    Raises:
        UndecodableJobError: The message does not decode; it carries only what is needed
            to fail the job back to its producer.
    """
    try:
        return Job(**message.model_dump())
    except ValidationError:
        # `from None`: the validation error quotes the job's fields, secrets included,
        # and a chained cause would carry it into any traceback that gets logged.
        raise UndecodableJobError(
            message.execution_id,
            reply_to_crew_channel=message.reply_to_crew_channel,
            # The session id may be the very field that failed to decode.
            session_id=message.session_id if isinstance(message.session_id, int) else None,
        ) from None


def encode_result(
    result: ExecutionResult, mutations: StorageMutations | None
) -> ExecutionResultMessage:
    """Encode the domain result (and any mutations) into the wire message."""
    mutations_message = None
    if mutations is not None:
        mutations_message = StorageMutationsMessage(
            org_prefix=mutations.org_prefix,
            session_id=mutations.session_id,
            mutations=mutations.mutations,
        )
    return ExecutionResultMessage(
        execution_id=result.execution_id,
        result=result.result,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        mutations=mutations_message,
        reply_to_crew_channel=result.reply_to_crew_channel,
        ran=result.ran,
        session_id=result.session_id,
        not_run_reason=result.not_run_reason,
    )
