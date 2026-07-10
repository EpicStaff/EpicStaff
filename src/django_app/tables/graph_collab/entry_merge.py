import copy


def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* onto *base*, returning a new dict.

    - When both values at a key are dicts, they are merged recursively.
    - Any other pairing (list, scalar, None, or a dict/non-dict type
      mismatch) — the overlay value replaces the base value whole.
    - Keys present in *base* but absent from *overlay* are preserved.
    - Neither *base* nor *overlay* is mutated; nested dicts in the result are
      copies, not shared references.
    """
    merged = copy.deepcopy(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            merged[key] = deep_merge(base_value, overlay_value)
        else:
            merged[key] = copy.deepcopy(overlay_value)
    return merged
