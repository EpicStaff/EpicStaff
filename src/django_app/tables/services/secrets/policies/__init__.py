"""Per-entity rules for what a write may not change without secrets:USE.

Adding a guarded entity: declare its policy in the module for its area -- a plain
`SecretPolicy(reference_fields=..., header_fields=...)` instance when it only lists
fields, a subclass instance when it decides a destination or records an approver --
add it to SECRET_POLICIES below, and set `secret_policy = <THE_POLICY>` on each
serializer that writes the entity (through SecretReferenceGuardMixin). A writer
without a serializer (import, quickstart) passes a RowWrite to SecretReferenceGuard.
A policy with an `approval_model` is also checked at injection time
(SecretInjectionGuard). test_secret_reference_coverage.py fails on an unregistered
policy and on a Secret field no policy guards.

Not re-exported from `tables.services.secrets`: policies import models, which that
package must not do at import time.
"""

from tables.services.secrets.policies.base import (
    CATALOG_DESTINATION,
    RowWrite,
    SecretPolicy,
    model_destination,
)
from tables.services.secrets.policies.embedding import (
    EMBEDDING_CONFIG_SECRET_POLICY,
    EMBEDDING_MODEL_SECRET_POLICY,
)
from tables.services.secrets.policies.llm import (
    LLM_CONFIG_SECRET_POLICY,
    LLM_MODEL_SECRET_POLICY,
    REALTIME_CONFIG_SECRET_POLICY,
    REALTIME_TRANSCRIPTION_CONFIG_SECRET_POLICY,
)
from tables.services.secrets.policies.quickstart import QUICKSTART_SECRET_POLICY
from tables.services.secrets.policies.realtime import (
    ELEVENLABS_REALTIME_CONFIG_SECRET_POLICY,
    GEMINI_REALTIME_CONFIG_SECRET_POLICY,
    OPENAI_REALTIME_CONFIG_SECRET_POLICY,
    TWILIO_CHANNEL_SECRET_POLICY,
)
from tables.services.secrets.policies.tools import (
    MCP_TOOL_SECRET_POLICY,
    PYTHON_CODE_SECRET_POLICY,
)
from tables.services.secrets.policies.triggers import (
    NGROK_WEBHOOK_CONFIG_SECRET_POLICY,
    TELEGRAM_TRIGGER_NODE_SECRET_POLICY,
    WEBHOOK_TRIGGER_SECRET_POLICY,
)

#: Every policy a writer may use.
SECRET_POLICIES: tuple[SecretPolicy, ...] = (
    ELEVENLABS_REALTIME_CONFIG_SECRET_POLICY,
    EMBEDDING_CONFIG_SECRET_POLICY,
    EMBEDDING_MODEL_SECRET_POLICY,
    GEMINI_REALTIME_CONFIG_SECRET_POLICY,
    LLM_CONFIG_SECRET_POLICY,
    LLM_MODEL_SECRET_POLICY,
    MCP_TOOL_SECRET_POLICY,
    NGROK_WEBHOOK_CONFIG_SECRET_POLICY,
    OPENAI_REALTIME_CONFIG_SECRET_POLICY,
    PYTHON_CODE_SECRET_POLICY,
    QUICKSTART_SECRET_POLICY,
    REALTIME_CONFIG_SECRET_POLICY,
    REALTIME_TRANSCRIPTION_CONFIG_SECRET_POLICY,
    TELEGRAM_TRIGGER_NODE_SECRET_POLICY,
    TWILIO_CHANNEL_SECRET_POLICY,
    WEBHOOK_TRIGGER_SECRET_POLICY,
)

__all__ = [
    "CATALOG_DESTINATION",
    "ELEVENLABS_REALTIME_CONFIG_SECRET_POLICY",
    "EMBEDDING_CONFIG_SECRET_POLICY",
    "EMBEDDING_MODEL_SECRET_POLICY",
    "GEMINI_REALTIME_CONFIG_SECRET_POLICY",
    "LLM_CONFIG_SECRET_POLICY",
    "LLM_MODEL_SECRET_POLICY",
    "MCP_TOOL_SECRET_POLICY",
    "NGROK_WEBHOOK_CONFIG_SECRET_POLICY",
    "OPENAI_REALTIME_CONFIG_SECRET_POLICY",
    "PYTHON_CODE_SECRET_POLICY",
    "QUICKSTART_SECRET_POLICY",
    "REALTIME_CONFIG_SECRET_POLICY",
    "REALTIME_TRANSCRIPTION_CONFIG_SECRET_POLICY",
    "SECRET_POLICIES",
    "TELEGRAM_TRIGGER_NODE_SECRET_POLICY",
    "TWILIO_CHANNEL_SECRET_POLICY",
    "WEBHOOK_TRIGGER_SECRET_POLICY",
    "RowWrite",
    "SecretPolicy",
    "model_destination",
]
