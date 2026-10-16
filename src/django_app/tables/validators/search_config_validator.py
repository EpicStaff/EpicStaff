from rest_framework import serializers

from tables.constants.knowledge_constants import PROPORTION_MAX

PROPORTION_SUM_TOLERANCE = 1e-9


def validate_proportion_sum(attrs: dict, first_field: str, second_field: str) -> None:
    """Reject two context proportions that together exceed 1; GraphRAG raises on them at search time.

    Skipped when either value is absent, so a partial update of one proportion is not rejected here.
    """
    first_value = attrs.get(first_field)
    second_value = attrs.get(second_field)
    if first_value is None or second_value is None:
        return
    # Same float tolerance as the frontend check, so 0.7 + 0.3 is accepted on both sides.
    if first_value + second_value > PROPORTION_MAX + PROPORTION_SUM_TOLERANCE:
        raise serializers.ValidationError(
            f"{first_field} + {second_field} must not exceed {PROPORTION_MAX:g}."
        )
