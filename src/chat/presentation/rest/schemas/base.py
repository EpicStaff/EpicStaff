from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

NUL_MESSAGE = "NUL (U+0000) characters are not allowed."


class BaseSchema(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


def refuse_nul(value: str) -> str:
    """Refuse U+0000, which Postgres TEXT and JSONB cannot store (the insert would fail with a 500)."""
    if "\x00" in value:
        raise ValueError(NUL_MESSAGE)
    return value


NulFreeStr = Annotated[str, AfterValidator(refuse_nul)]
