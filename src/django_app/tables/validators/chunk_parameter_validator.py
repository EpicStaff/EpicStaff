from typing import Any, Dict, List, Optional

from tables.constants.knowledge_constants import (
    FILE_TYPE_SPECIFIC_STRATEGIES,
    MAX_CHUNK_OVERLAP,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_OVERLAP,
    MIN_CHUNK_SIZE,
    UNIVERSAL_STRATEGIES,
)
from tables.exceptions import InvalidChunkParametersException
from tables.models.knowledge_models import NaiveRagDocumentConfig


class NaiveRagDocumentConfigValidator:
    """Single source of NaiveRagDocumentConfig chunk-parameter validation and
    update-dict building (size / overlap / strategy↔file-type).

    Shared by the single-update and bulk-update paths so both apply identical
    rules. Errors are returned as a list of ``{field, value, reason}`` dicts
    (empty list = OK), matching the structured-error contract used elsewhere:
      - bulk-update collects errors per config (partial success);
      - single-update calls :meth:`validate_or_raise`.
    """

    @staticmethod
    def allowed_strategies_for_file_type(file_type: str) -> set:
        """Return the set of chunk strategies valid for a given file type.

        Business rules:
        - token, character: allowed for ALL file types
        - json: only for JSON files
        - markdown: only for MD files
        - html: only for HTML files
        - csv: only for CSV files
        """
        return UNIVERSAL_STRATEGIES | FILE_TYPE_SPECIFIC_STRATEGIES.get(
            file_type, set()
        )

    @classmethod
    def is_strategy_allowed(cls, strategy: str, file_type: str) -> bool:
        """Return True iff ``strategy`` is in the allowed set for ``file_type``."""
        return strategy in cls.allowed_strategies_for_file_type(file_type)

    @staticmethod
    def build_updates(
        chunk_size: Optional[int],
        chunk_overlap: Optional[int],
        chunk_strategy: Optional[str],
        additional_params: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Keep only the params that were actually supplied (non-None)."""
        pairs = (
            ("chunk_size", chunk_size),
            ("chunk_overlap", chunk_overlap),
            ("chunk_strategy", chunk_strategy),
            ("additional_params", additional_params),
        )
        return {k: v for k, v in pairs if v is not None}

    @staticmethod
    def _error(field: str, value: Any, reason: str) -> Dict[str, Any]:
        return {"field": field, "value": value, "reason": reason}

    @classmethod
    def _validate_range(
        cls, field: str, value: Any, low: int, high: int
    ) -> List[Dict[str, Any]]:
        if value < low:
            return [cls._error(field, value, f"{field} too small (min {low})")]
        if value > high:
            return [cls._error(field, value, f"{field} too large (max {high})")]
        return []

    @classmethod
    def _validate_chunk_size(
        cls, value: Any, config: Optional[NaiveRagDocumentConfig] = None
    ) -> List[Dict[str, Any]]:
        return cls._validate_range("chunk_size", value, MIN_CHUNK_SIZE, MAX_CHUNK_SIZE)

    @classmethod
    def _validate_chunk_overlap(
        cls, value: Any, config: Optional[NaiveRagDocumentConfig] = None
    ) -> List[Dict[str, Any]]:
        return cls._validate_range(
            "chunk_overlap", value, MIN_CHUNK_OVERLAP, MAX_CHUNK_OVERLAP
        )

    @classmethod
    def _validate_chunk_strategy(
        cls, value: Any, config: Optional[NaiveRagDocumentConfig] = None
    ) -> List[Dict[str, Any]]:
        valid_strategies = [
            choice[0] for choice in NaiveRagDocumentConfig.ChunkStrategy.choices
        ]
        if value not in valid_strategies:
            return [
                cls._error(
                    "chunk_strategy",
                    value,
                    f"Invalid chunk_strategy. Must be one of: {', '.join(valid_strategies)}",
                )
            ]
        if config and not cls.is_strategy_allowed(value, config.document.file_type):
            allowed = cls.allowed_strategies_for_file_type(config.document.file_type)
            return [
                cls._error(
                    "chunk_strategy",
                    value,
                    f"chunk_strategy '{value}' is not valid for file type '{config.document.file_type}'. Allowed: {', '.join(sorted(allowed))}",
                )
            ]
        return []

    @classmethod
    def validate_field(
        cls,
        field_name: str,
        value: Any,
        config: Optional[NaiveRagDocumentConfig] = None,
    ) -> List[Dict[str, Any]]:
        """Validate a single field via per-field dispatch. Returns
        ``{field, value, reason}`` dicts (empty list if valid, or if the field
        has no validator). ``config`` is needed for strategy↔file-type."""
        validator = {
            "chunk_size": cls._validate_chunk_size,
            "chunk_overlap": cls._validate_chunk_overlap,
            "chunk_strategy": cls._validate_chunk_strategy,
        }.get(field_name)
        return validator(value, config) if validator else []

    @classmethod
    def collect_errors(
        cls, config: NaiveRagDocumentConfig, updates: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Per-field + cross-field (overlap < size) validation against the
        config's effective post-update values. Empty list = OK."""
        errors: List[Dict[str, Any]] = []
        for field in ("chunk_size", "chunk_overlap"):
            if field in updates:
                errors.extend(cls.validate_field(field, updates[field]))
        if "chunk_strategy" in updates:
            errors.extend(
                cls.validate_field("chunk_strategy", updates["chunk_strategy"], config)
            )

        final_size = updates.get("chunk_size", config.chunk_size)
        final_overlap = updates.get("chunk_overlap", config.chunk_overlap)
        if final_overlap >= final_size:
            errors.append(
                {
                    "field": "chunk_overlap",
                    "value": final_overlap,
                    "reason": (
                        f"chunk_overlap ({final_overlap}) must be less than "
                        f"chunk_size ({final_size})"
                    ),
                }
            )
        return errors

    @classmethod
    def validate_or_raise(
        cls, config: NaiveRagDocumentConfig, updates: Dict[str, Any]
    ) -> None:
        """Single-update convenience: raise with the full error list if invalid."""
        errors = cls.collect_errors(config, updates)
        if errors:
            raise InvalidChunkParametersException(errors=errors)
