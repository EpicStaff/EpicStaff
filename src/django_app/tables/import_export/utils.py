import re
from typing import List, Optional

from django.conf import settings

from tables.models import Organization, PythonCode


def ensure_unique_identifier(base_name: str, existing_names: List[str]) -> str:
    """
    Creates new unique name from base_name using a trailing "#N" suffix.

    If base_name is already unique it is returned unchanged. Otherwise any
    existing "#N" (or "# N") suffix is stripped to get the base, and the lowest
    free number is appended, e.g. "My Node" -> "My Node #2",
    "Node #4" -> "Node #5".
    """
    if base_name not in existing_names:
        return base_name

    match = re.match(r"^(.+?)\s*#\s*\d+$", base_name.strip())
    if match:
        clean_base = match.group(1)
    else:
        clean_base = base_name.strip()

    existing_numbers = set()
    pattern = re.compile(rf"^{re.escape(clean_base)}\s*#\s*(\d+)$")

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

    return f"{clean_base} #{i}"


def create_filters(data: dict) -> tuple[dict, dict]:
    """Get fields from given data and separate filters for isnull fields and actual values"""
    filters, null_filters = {}, {}

    for field, value in data.items():
        if value is None:
            null_filters[f"{field}__isnull"] = True
        else:
            filters[field] = value

    return filters, null_filters


def resolve_import_organization(org_id: Optional[int]) -> Optional[Organization]:
    """
    Resolves the organization an imported entity should be stamped with.

    Prefers the active `org_id` passed into the import. Falls back to the
    default organization when no `org_id` is given (or it does not match an
    existing organization), anchoring on `is_default=True` first since that
    flag survives a rename, then on `name__iexact` against
    `settings.DEFAULT_ORGANIZATION_NAME` for orgs never flagged as default.
    Mirrors `SuperadminBootstrapService._get_or_create_default_org`. Never
    raises `Organization.DoesNotExist`.
    """
    if org_id is not None:
        organization = Organization.objects.filter(id=org_id).first()
        if organization is not None:
            return organization

    organization = Organization.objects.filter(is_default=True).first()
    if organization is not None:
        return organization

    return Organization.objects.filter(
        name__iexact=settings.DEFAULT_ORGANIZATION_NAME
    ).first()


def python_code_equal(code_instance: PythonCode, code_data: dict):
    """Compares instance of PythonCode with incoming python code data. Returns True if both are equal"""
    return all(
        [
            code_instance.libraries == code_data.get("libraries"),
            (code_instance.code.rstrip() + "\n")
            == (code_data.get("code").rstrip() + "\n"),
            code_instance.entrypoint == code_data.get("entrypoint"),
            code_instance.global_kwargs == code_data.get("global_kwargs"),
        ]
    )
