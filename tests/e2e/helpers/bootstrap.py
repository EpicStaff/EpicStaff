"""Bootstrap data shared by conftest.py and test_auth_rbac.py."""

import secrets
import uuid
from dataclasses import dataclass, field

import httpx

from helpers.redaction import REDACTED, Secret, protect, redact, register_secret

EMAIL_DOMAIN = "e2e.example.com"
API_KEY_PREFIX = "es-"

# The minimum the suite needs; `secrets` has no `update` in rbac/access/catalog.py.
FULL_CRUD = ["create", "read", "update", "delete"]
RUNNER_ROLE_PERMISSIONS = [
    {"resource_type": "flows", "actions": FULL_CRUD},
    {"resource_type": "agents", "actions": FULL_CRUD},
    {"resource_type": "surfaces", "actions": FULL_CRUD},
    {"resource_type": "knowledge_sources", "actions": FULL_CRUD},
    {"resource_type": "files", "actions": FULL_CRUD},
    {"resource_type": "llm_configs", "actions": ["create", "read", "update"]},
    {"resource_type": "secrets", "actions": ["create", "read", "use"]},
]


@dataclass(frozen=True)
class StepResponse:
    """A bootstrap response with credentials redacted, safe to print in assertions."""

    status_code: int
    body: object


@dataclass
class Bootstrap:
    """What the bootstrap chain created. Credentials are `Secret`s: `repr` never shows them."""

    org_id: int = 0
    role_id: int = 0
    superadmin_user_id: int = 0
    user_id: int = 0
    superadmin_email: str = ""
    user_email: str = ""
    api_key_has_expected_prefix: bool = False
    steps: dict[str, StepResponse] = field(default_factory=dict)
    last_step: str | None = None
    superadmin_password: Secret = field(default=Secret(""), repr=False)
    user_api_key: Secret = field(default=Secret(""), repr=False)

    def record(self, step: str, response: httpx.Response) -> dict:
        """Store the redacted response; return the body with credentials as `Secret`s."""
        body = protect(response.json())
        self.steps[step] = StepResponse(response.status_code, redact(body))
        self.last_step = step
        return body

    def describe_last_step(self) -> str:
        if self.last_step is None:
            return "no step recorded yet"
        step = self.steps[self.last_step]
        return f"last recorded step {self.last_step!r}: {step.status_code} {step.body!r}"


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def new_password() -> Secret:
    """A password the validators accept: long, mixed, not common, unlike the email."""
    return register_secret(f"Pw!{secrets.token_urlsafe(18)}")


__all__ = [
    "API_KEY_PREFIX",
    "EMAIL_DOMAIN",
    "REDACTED",
    "RUNNER_ROLE_PERMISSIONS",
    "Bootstrap",
    "StepResponse",
    "new_password",
    "unique_suffix",
]
