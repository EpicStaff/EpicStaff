import re

from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.services.copy_services.base_copy_service import BaseCopyService

_NUMBER_SUFFIX = re.compile(r"^(?P<base>.+) \((?P<number>\d+)\)$")


def next_free_preset_name(org_id: int | None, name: str) -> str:
    """Return `name`, or the first free "<base> (N)" (N >= 2) if it is taken in the org.

    A trailing " (N)" on `name` is stripped first, so copying "Filter (2)" gives
    "Filter (3)", not "Filter (2) (2)". Shared by copy and import so both number alike.
    """
    taken = set(AuditFilterPreset.objects.filter(org_id=org_id).values_list("name", flat=True))
    if name not in taken:
        return name

    match = _NUMBER_SUFFIX.match(name)
    base = match.group("base") if match else name
    max_length = AuditFilterPreset._meta.get_field("name").max_length
    number = 2
    while True:
        suffix = f" ({number})"
        # Cut the base so the numbered name still fits the column.
        candidate = f"{base[: max_length - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        number += 1


class AuditFilterPresetCopyService(BaseCopyService):
    """Copy service for AuditFilterPreset.

    The copy's name is unique within the target org (see next_free_preset_name),
    matching the model's (org, name) constraint; the copy belongs to `created_by`.
    """

    def copy(
        self,
        preset: AuditFilterPreset,
        name: str | None = None,
        org_id: int | None = None,
        created_by=None,
    ) -> AuditFilterPreset:
        target_org_id = org_id if org_id is not None else preset.org_id
        target_created_by = created_by if created_by is not None else preset.created_by

        return AuditFilterPreset.objects.create(
            org_id=target_org_id,
            created_by=target_created_by,
            name=next_free_preset_name(target_org_id, name or preset.name),
            filter_body=preset.filter_body,
        )
