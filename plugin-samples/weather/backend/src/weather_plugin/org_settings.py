"""The organization's Weather settings: the LLM config Weather writes its summaries with.

An admin sets it up on Weather's Organization settings page. Weather then creates, on behalf
of that admin, a Secret holding the key they entered and an LLM config that uses it. Secrets
cannot be changed, and Weather may not delete them, so it is set up once; an admin changes
it in EpicStaff's own settings.

An attempt can fail between the two creates, leaving the Secret without its config. The next
attempt then uses that Secret when it holds the key the admin enters again: EpicStaff shows the
last four characters of every Secret of nine characters or more, and they must match. A Secret
of that name with another key is never used, since Weather cannot read or replace its value;
the admin is asked to delete it first.
"""

from typing import Any

from epicstaff_plugin.client import EpicStaffApiError, OrgClient

LLM_CONFIG_NAME = "Weather summaries"
SECRET_NAME = "Weather · LLM key"
PAGE_SIZE = 200
# Lists are read page by page up to this many rows.
MAX_LISTED = 2000
# EpicStaff's `tail` of a Secret: its last characters, for values of at least the minimum length.
SECRET_TAIL_LENGTH = 4
SECRET_TAIL_MIN_VALUE_LENGTH = 9


class AlreadyConfigured(Exception):  # noqa: N818 (named after the route's answer code)
    """The organization already has Weather's LLM config."""


class UnknownModel(Exception):  # noqa: N818 (named after what it is)
    """The organization cannot see an LLM model with that id."""


class SecretExists(Exception):  # noqa: N818 (named after the route's answer code)
    """A Secret with Weather's name exists without the config, and not with the entered key."""

    message = (
        f'A Secret named "{SECRET_NAME}" already exists with another key. Delete it in '
        "Settings → Secrets, then set up the LLM again."
    )


async def find_llm_config(epicstaff: OrgClient) -> dict[str, object] | None:
    """Return Weather's LLM config in the organization as `{"id", "name"}`, or None."""
    page = await epicstaff.get("llm-configs/", params={"custom_name": LLM_CONFIG_NAME, "limit": 1})
    configs = page["results"]
    if not configs:
        return None
    return {"id": configs[0]["id"], "name": configs[0]["custom_name"]}


async def list_llm_models(epicstaff: OrgClient) -> list[dict[str, object]]:
    """Return the LLM models the organization can see, as `{"id", "name"}`."""
    return [
        {"id": model["id"], "name": model["name"]}
        for model in await _read_pages(epicstaff, "llm-models/")
    ]


async def find_secret(epicstaff: OrgClient) -> dict[str, Any] | None:
    """Return the organization's Secret named "Weather · LLM key" as `{"id", "tail"}`, or None."""
    for secret in await _read_pages(epicstaff, "secrets/"):
        if secret["name"] == SECRET_NAME:
            return {"id": secret["id"], "tail": secret.get("tail") or ""}
    return None


async def configure_llm(epicstaff: OrgClient, llm_model_id: int, api_key: str) -> dict[str, object]:
    """Create the Secret and the LLM config that uses it; return the config as `{"id", "name"}`.

    A Secret an earlier attempt left without its config is used when it holds the same key.

    Raises:
        AlreadyConfigured: The organization already has Weather's LLM config.
        UnknownModel: The organization cannot see the model.
        SecretExists: A Secret with Weather's name holds another key.
        EpicStaffApiError: EpicStaff refused to create the Secret or the config.
    """
    if await find_llm_config(epicstaff) is not None:
        raise AlreadyConfigured
    try:
        await epicstaff.get(f"llm-models/{llm_model_id}/")
    except EpicStaffApiError as error:
        if error.status == 404:
            raise UnknownModel from None
        raise
    secret = await find_secret(epicstaff)
    if secret is None:
        secret = await epicstaff.post("secrets/", {"name": SECRET_NAME, "value": api_key})
    elif not _holds_key(secret, api_key):
        raise SecretExists
    config = await epicstaff.post(
        "llm-configs/",
        {"custom_name": LLM_CONFIG_NAME, "model": llm_model_id, "api_key_secret_id": secret["id"]},
    )
    return {"id": config["id"], "name": config["custom_name"]}


def _holds_key(secret: dict[str, Any], api_key: str) -> bool:
    return (
        len(api_key) >= SECRET_TAIL_MIN_VALUE_LENGTH
        and len(secret["tail"]) == SECRET_TAIL_LENGTH
        and secret["tail"] == api_key[-SECRET_TAIL_LENGTH:]
    )


async def _read_pages(epicstaff: OrgClient, path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while len(rows) < MAX_LISTED:
        page = await epicstaff.get(path, params={"limit": PAGE_SIZE, "offset": len(rows)})
        rows.extend(page["results"])
        if not page["results"] or page.get("next") is None:
            break
    return rows
