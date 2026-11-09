from rest_framework import serializers
from tables.models import TransferJob
from tables.serializers.serializers import SessionExportAllSerializer
from tables.serializers.utils.bulk_ids import StrictPositiveIntegerField
from tables.serializers.utils.list_fields import BoundedListField

# Largest number of items one export job may carry, the same as one bulk request.
EXPORT_JOB_MAX_IDS = 500
# Largest number of sessions one session export may carry, picked or matched by filters.
SESSION_EXPORT_MAX_IDS = 10000

EXPORT_FORMATS = ("json", "csv")


class ExportJobCreateSerializer(serializers.Serializer):
    """Body of an `export-jobs` action that takes only the items to export.

    Knowledge collections, tools, MCP tools and audit filter presets.
    """

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


class SessionExportJobCreateSerializer(SessionExportAllSerializer):
    """Body of `POST /api/sessions/export-jobs/`: either `ids`, or the filters of the session list.

    Without `ids`, every top-level session matching the filters is exported (no
    filter at all exports every session of the organization).
    """

    ids = BoundedListField(
        child=StrictPositiveIntegerField(),
        allow_empty=False,
        required=False,
        max_length=SESSION_EXPORT_MAX_IDS,
        help_text=f"IDs of the sessions to export, at most {SESSION_EXPORT_MAX_IDS}. "
        "Leave out to export the sessions matching the filters instead.",
    )
    export_format = serializers.ChoiceField(
        choices=EXPORT_FORMATS,
        default="json",
        help_text="`json` puts `sessions.json` into the archive, `csv` puts `sessions.csv` "
        "(one row per session message).",
    )

    def validate_ids(self, ids: list[int]) -> list[int]:
        return list(dict.fromkeys(ids))

    def validate(self, attrs):
        filters = set(attrs) - {"ids", "export_format"}
        if "ids" in attrs and filters:
            raise serializers.ValidationError(
                f"Send either ids or filters, not both (got {', '.join(sorted(filters))})."
            )
        return attrs


class ClassificationDecisionTableExportJobCreateSerializer(serializers.Serializer):
    """Body of `POST /api/classification-decision-table-node/export-jobs/`: one node."""

    ids = BoundedListField(
        child=StrictPositiveIntegerField(),
        allow_empty=False,
        max_length=1,
        help_text="The ID of the one node to export.",
    )
    export_format = serializers.ChoiceField(
        choices=EXPORT_FORMATS,
        default="json",
        help_text="`json` puts `export.json` into the archive, a file `partial-import` takes; "
        "`csv` puts a readable CSV of the node's rules.",
    )


class ExportJobCreatedSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()


class TransferJobDownloadTicketSerializer(serializers.Serializer):
    download_url = serializers.CharField(
        help_text="Path of the archive download, carrying a one-time `ticket`; "
        "needs no Authorization header."
    )


class TransferJobsClearedSerializer(serializers.Serializer):
    deleted = serializers.IntegerField(help_text="Number of jobs removed; 0 when none was.")


class _ImportJobQuerySerializer(serializers.Serializer):
    """Query parameters of an import-job upload; a parameter it does not declare is refused.

    Validate a plain dict (`request.query_params.dict()`), not the QueryDict: DRF reads
    an absent boolean of a QueryDict as false instead of applying its default.
    """

    file_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Name of the uploaded file, shown in the job list. The body is raw, "
        "so it carries no name of its own.",
    )

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
    """Query of `POST /api/source-collections/import-jobs/`: only the file name."""


class TransferJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransferJob
        fields = [
            "id",
            "kind",
            "main_entity",
            "display_name",
            "status",
            "file_name",
            "result",
            "error",
            "created_at",
            "finished_at",
            "expires_at",
        ]
        read_only_fields = fields


class TransferJobListQuerySerializer(serializers.Serializer):
    """Query of `GET /api/transfer-jobs/`; every filter is optional."""

    status = serializers.ListField(
        child=serializers.ChoiceField(choices=TransferJob.Status.choices),
        required=False,
        help_text="Repeat to keep jobs in any of several statuses.",
    )
    kind = serializers.ChoiceField(choices=TransferJob.Kind.choices, required=False)
