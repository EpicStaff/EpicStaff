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


class TransferJobDownloadTicketSerializer(serializers.Serializer):
    download_url = serializers.CharField(
        help_text="Path of the archive download, carrying a one-time `ticket`; "
        "needs no Authorization header."
    )


class _ImportJobQuerySerializer(serializers.Serializer):
    """Query parameters of an import-job upload; a parameter it does not declare is refused.

    Validate a plain dict (`request.query_params.dict()`), not the QueryDict: DRF reads
    an absent boolean of a QueryDict as false instead of applying its default.
    """

    def validate(self, attrs):
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(dict.fromkeys(unknown, "Unknown query parameter."))
        return attrs


class FlowImportJobQuerySerializer(_ImportJobQuerySerializer):
    """Query of `POST /api/graphs/import-jobs/`: the import settings, as the `import/` form has them."""

    preserve_uuids = serializers.BooleanField(default=False)
    replace_existing = serializers.BooleanField(default=False)
    import_labels = serializers.BooleanField(default=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["replace_existing"] and not attrs["preserve_uuids"]:
            raise serializers.ValidationError(
                {"replace_existing": "replace_existing=True requires preserve_uuids=True."}
            )
        return attrs


class CollectionImportJobQuerySerializer(_ImportJobQuerySerializer):
    """Query of `POST /api/source-collections/import-jobs/`: it takes no parameters."""


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
