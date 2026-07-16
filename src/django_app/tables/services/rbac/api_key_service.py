from loguru import logger

from tables.models.rbac_models import ApiKey


class ApiKeyService:
    """Mints a self-service ApiKey owned by the calling user.

    The raw key is generated once and hashed via `ApiKey.set_key` before the
    row is persisted — the raw value itself is never stored, so the caller
    (view layer) must hand it back to the user in the same response.
    """

    def create_for_user(self, *, user, name: str, scopes: list[str]) -> tuple[ApiKey, str]:
        raw_key = ApiKey.generate_raw_key()
        api_key = ApiKey(name=name, scopes=scopes, created_by=user)
        api_key.set_key(raw_key)
        api_key.save()

        logger.info(
            "ApiKey created by user_id={user_id} name={name} key_prefix={prefix}",
            user_id=user.id,
            name=name,
            prefix=api_key.prefix,
        )

        return api_key, raw_key
