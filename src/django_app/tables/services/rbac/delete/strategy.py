from abc import ABC, abstractmethod


class DeleteStrategy(ABC):
    """Target-specific half of a permanent delete."""

    target_type: str

    @abstractmethod
    def get_instance(self, target_id: int):
        """Load the target row, raising the target's not-found exception."""

    @abstractmethod
    def validate(self, instance, *, actor) -> None:
        """Raise a blocker exception when this target must not be deleted."""

    def validate_locked(self, instance, *, actor) -> None:
        """Re-check blockers under a row lock, inside the delete transaction."""
        return None

    @abstractmethod
    def describe(self, instance) -> dict:
        """Return the report's `target` block for this instance."""

    def external_artifacts(self, instance) -> list[dict]:
        """Describe files outside the database that this delete orphans."""
        return []

    def snapshot(self, instance) -> dict:
        """Capture what post-commit cleanup needs before the row disappears."""
        return {}

    def pre_delete(self, instance) -> None:
        """Run inside the delete transaction, before the cascade."""
        return None

    def cleanup_external(self, snapshot: dict) -> None:
        """Remove orphaned external files, after the transaction commits."""
        return None
