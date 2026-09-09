"""Constants shared between `sandbox` (publisher of credential requests) and
`django_app` (the credential issuer that consumes them). Both sides must
agree on the exact Redis Stream name and envelope `type` value -- if either
were changed on only one side, sandbox's requests would silently stop being
recognized by the issuer.
"""

# Redis Stream carrying credential-issuance requests (sandbox -> issuer).
STORAGE_CREDENTIAL_REQUEST_STREAM = "storage_credential_requests"

# `StreamEnvelope.type` value stamped on every credential-issuance request.
STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE = "issue_temporary_credential"
