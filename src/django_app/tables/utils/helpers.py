import re
from datetime import datetime


def natural_sort_key(s: str) -> list:
    """Sort key that compares embedded numbers numerically: 'label2' < 'label10'."""
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", s)
    ]


def get_label_descendant_ids(label_id: int) -> set[int]:
    """Return the given label ID plus all descendant label IDs (one DB query)."""
    from tables.models.label_models import Label

    all_labels = Label.objects.values("id", "parent_id")
    children_map: dict[int, list[int]] = {}
    for row in all_labels:
        if row["parent_id"] is not None:
            children_map.setdefault(row["parent_id"], []).append(row["id"])
    result: set[int] = set()
    queue = [label_id]
    while queue:
        current = queue.pop()
        result.add(current)
        queue.extend(children_map.get(current, []))
    return result


def generate_file_name(
    base_name: str, prefix: str = "", default_name: str = "export"
) -> str:
    """
    Creates safe json file name with timestamp.
    If `base_name` cannot be sanitized, function falls back to `default_name`
    """
    safe_name = base_name.lower()

    safe_name = re.sub(r'[<>:"/\\|?*]+', "", safe_name)
    safe_name = re.sub(r"[^a-z0-9_]", "_", safe_name.lower())
    safe_name = re.sub(r"_+", "_", safe_name).strip("_")

    if not safe_name:
        safe_name = default_name

    timestamp = datetime.now().strftime("%Y-%m-%d")
    return f"{prefix}_{safe_name}_{timestamp}.json"


def generate_new_unique_name(base_name: str, existing_names: list[str]):
    """
    Creates new unique name from base_name.
    """
    if base_name not in existing_names:
        return base_name

    match = re.match(r"^(.+?)\s*\(\d+\)$", base_name.strip())
    if match:
        clean_base = match.group(1)
    else:
        clean_base = base_name.strip()

    if clean_base not in existing_names:
        return clean_base

    existing_numbers = set()
    pattern = re.compile(rf"^{re.escape(clean_base)}\s*\((\d+)\)$")

    for name in existing_names:
        if name == clean_base:
            existing_numbers.add(1)
        else:
            match = pattern.match(name)
            if match:
                existing_numbers.add(int(match.group(1)))

    i = 2
    while i in existing_numbers:
        i += 1

    return f"{clean_base} ({i})"
