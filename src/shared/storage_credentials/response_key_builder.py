"""Builds the Redis key used to transport temporary credential responses from
the issuer (running in `django_app`) back to the requestor (running in
`sandbox`).

The response is transported via a Redis List + BLPOP, not Pub/Sub: unlike a
Pub/Sub message published with no subscriber listening (lost forever), a value
RPUSHed to a list key persists there until something BLPOPs it, so this does
not have Pub/Sub's "publish arrived before subscribe" failure mode.

This is the single source of truth for the response key format. Both `sandbox`
(the requestor) and `django_app` (the issuer) must import this same function,
so the key they build is identical.
"""

CREDENTIAL_RESPONSE_KEY_PREFIX = "storage_credential_response"


def response_key(execution_id: str) -> str:
    """Build the Redis key for a credential response.

    Args:
        execution_id: The execution ID of the code task requesting credentials.

    Returns:
        The Redis key where the issuer will push the credential response.
    """
    return f"{CREDENTIAL_RESPONSE_KEY_PREFIX}:{execution_id}"
