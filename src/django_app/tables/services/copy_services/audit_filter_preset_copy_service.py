from tables.import_export.utils import ensure_unique_identifier
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.services.copy_services.base_copy_service import BaseCopyService


class AuditFilterPresetCopyService(BaseCopyService):
    """Copy service for AuditFilterPreset.

    Owner-scoped, unlike every other copy service here: uniqueness for the
    auto-numbered name is checked against (org, created_by), matching the
    model's own unique constraint - not just org - so two different users
    can each have their own "My Filter" / "My Filter #2" without colliding.
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

        existing_names = list(
            AuditFilterPreset.objects.filter(
                org_id=target_org_id, created_by=target_created_by
            ).values_list("name", flat=True)
        )
        new_name = ensure_unique_identifier(
            base_name=name if name else preset.name,
            existing_names=existing_names,
        )

        return AuditFilterPreset.objects.create(
            org_id=target_org_id,
            created_by=target_created_by,
            name=new_name,
            filter_body=preset.filter_body,
        )
