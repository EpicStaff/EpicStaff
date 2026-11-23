"""Read the `{type, errors: [{code, detail, attr, context}]}` body every error answer has."""


def details_by_attr(body: dict) -> dict[str | None, list[str]]:
    """Map each `attr` an error answer names (None for a whole-request error) to its details."""
    details: dict[str | None, list[str]] = {}
    for item in body["errors"]:
        details.setdefault(item["attr"], []).append(item["detail"])
    return details


def error_codes(body: dict) -> list[str]:
    return [item["code"] for item in body["errors"]]


def attr_details(body: dict) -> list[dict]:
    """Each error item as `{attr, detail}`, in order: what a problem list compares on."""
    return [{"attr": item["attr"], "detail": item["detail"]} for item in body["errors"]]


def error_text(body: dict) -> str:
    """Every error item as `attr: detail` (just `detail` without an attr), joined by "; "."""
    return "; ".join(
        f"{item['attr']}: {item['detail']}" if item["attr"] else item["detail"]
        for item in body["errors"]
    )
