from datetime import datetime
from typing import Annotated, Any

from common.utils import INTEGER_COLUMN_MAX, utcnow
from pydantic import AfterValidator, AwareDatetime, BeforeValidator, Field

from presentation.rest.schemas.base import BaseSchema


def _json_integer(value: Any) -> Any:
    # Litestar validates request bodies in lax mode, which overrides a field's Strict(): `true`
    # would read as org 1 and "1" as an integer.
    if isinstance(value, bool) or not isinstance(value, int):
        # ValueError, not TypeError: pydantic turns only the former into a 400.
        raise ValueError("must be a JSON integer")  # noqa: TRY004
    return value


def _not_in_the_future(value: datetime) -> datetime:
    # A future cutoff would delete conversations closed moments ago: always a caller's bug.
    if value > utcnow():
        raise ValueError("must not be in the future")
    return value


OrgId = Annotated[int, BeforeValidator(_json_integer), Field(gt=0, le=INTEGER_COLUMN_MAX)]
PastCutoff = Annotated[AwareDatetime, AfterValidator(_not_in_the_future)]


class RetentionPurgeInput(BaseSchema):
    org_id: OrgId = Field(description="The organization whose conversations expire.")
    older_than: PastCutoff = Field(
        description=(
            "ISO-8601 with a UTC offset, not in the future. Closed conversations whose last "
            "message, or creation when they have none, is before it are deleted."
        )
    )
