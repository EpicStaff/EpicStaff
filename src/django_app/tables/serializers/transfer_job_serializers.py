from rest_framework import serializers
from tables.models import TransferJob
from tables.serializers.utils.bulk_ids import StrictPositiveIntegerField
from tables.serializers.utils.list_fields import BoundedListField

# Largest number of items one export job may carry, the same as one bulk request.
EXPORT_JOB_MAX_IDS = 500


class ExportJobCreateSerializer(serializers.Serializer):
    """Body of `POST /api/source-collections/export-jobs/`: the items to export."""

    ids = BoundedListField(
        child=StrictPositiveIntegerField(),
        allow_empty=False,
        max_length=EXPORT_JOB_MAX_IDS,
        help_text=f"IDs of the items to export, at most {EXPORT_JOB_MAX_IDS}.",
    )

    def validate_ids(self, ids: list[int]) -> list[int]:
        # The job compares the number of rows found against len(ids), so a
        # repeated id would otherwise be reported as a missing item.
        return list(dict.fromkeys(ids))


class FlowExportJobCreateSerializer(ExportJobCreateSerializer):
    """Body of `POST /api/graphs/export-jobs/`."""

    include_knowledge = serializers.BooleanField(
        default=True,
        help_text="Carry the knowledge collections the flows' nodes use, with their files.",
    )


class ExportJobCreatedSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()


class TransferJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferJob
        fields = [
            "id",
            "kind",
            "main_entity",
            "status",
            "file_name",
            "result",
            "error",
            "created_at",
            "finished_at",
            "expires_at",
        ]
        read_only_fields = fields
