"""Single source of truth for constants that must agree across every
storage-credential participant: `sandbox`, `django_app` (the issuer), and
the trusted scope publishers (`crew`, `agent`, `realtime`, django's own
Test run path). If any of these values drifted between participants,
requests or scopes would silently stop being recognized.
"""

# Redis Stream carrying credential-issuance requests (sandbox -> issuer).
STORAGE_CREDENTIAL_REQUEST_STREAM = "storage_credential_requests"

# `StreamEnvelope.type` value stamped on every credential-issuance request.
STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE = "issue_temporary_credential"

# How long the trusted scope written by a publisher survives before a
# never-consumed request is presumed abandoned.
CREDENTIAL_SCOPE_TTL_SECONDS = 900

# How long sandbox's credential-wait client blocks on BLPOP before treating
# the issuer as unreachable and failing closed.
STORAGE_CREDENTIAL_WAIT_TIMEOUT_S = 15
