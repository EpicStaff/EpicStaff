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


def merge_entry(base: dict, overlay: dict) -> dict:
    """Merge a partial-op overlay onto a snapshot entry"""

    merged = copy.deepcopy(base)
    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if (
            key == "metadata"
            and isinstance(base_value, dict)
            and isinstance(overlay_value, dict)
        ):
            merged[key] = deep_merge(base_value, overlay_value)
        else:
            merged[key] = copy.deepcopy(overlay_value)
    return merged


def find_mismatched_keys(base: dict, expected: dict) -> list[str]:
    """Return the top-level keys of *expected* whose value doesn't match *base*"""

    mismatched: list[str] = []
    for key, expected_value in expected.items():
        if key == "metadata" and isinstance(expected_value, dict):
            base_metadata = base.get("metadata")
            if not isinstance(base_metadata, dict):
                base_metadata = {}
            for sub_key, expected_sub_value in expected_value.items():
                base_sub_value = base_metadata.get(sub_key)
                if base_sub_value != expected_sub_value:
                    mismatched.append(f"metadata.{sub_key}")
            continue

        base_value = base.get(key)
        if base_value != expected_value:
            mismatched.append(key)
    return mismatched
