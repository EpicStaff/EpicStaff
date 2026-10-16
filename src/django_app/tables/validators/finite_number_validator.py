import math

from django.core.exceptions import ValidationError


def validate_finite_number(value: float) -> None:
    """Reject NaN and infinity, which min/max validators let through and JSON cannot render.

    Every comparison with NaN is false, so ``MinValueValidator``/``MaxValueValidator`` never
    trip on it, and DRF's ``FloatField`` parses the strings ``"nan"``/``"inf"``.
    """
    if not math.isfinite(value):
        raise ValidationError("Must be a finite number.", code="invalid")
