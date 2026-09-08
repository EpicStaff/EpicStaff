from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy.sql import expression


class SoftDeleteColumnsMixin:
    """Mirrors tables.models.base_models.SoftDeleteFields on the SQLAlchemy side.
    Fields only — no business logic (deletion is owned by Django)."""

    is_soft_deleted = Column(
        Boolean, nullable=False, default=False, server_default=expression.false()
    )
    soft_deleted_at = Column(DateTime, nullable=True)
