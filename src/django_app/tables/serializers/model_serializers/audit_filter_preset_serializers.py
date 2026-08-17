from rest_framework import serializers

from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.serializers.org_scoped_fields import resolve_active_org_id


#  Mirrors SessionSearchRequest's own field set (src/auditor/app/controllers/
# query_routes.py) - keep these two in sync if that shape ever changes.
_FILTER_BODY_KEY_TYPES: dict[str, type] = {
    "filters": dict,
    "query": str,
    "match_scope": dict,
    "cursor": str,
    "size": int,
}


def _validate_filter_body(value):
    """
    filter_body must be a JSON object matching the search request body
    shape ({"filters": FilterNode} | {"query": str}, optionally with
    match_scope/cursor/size) - not just any dict. Checked here: known keys
    only, and each present key has the right JSON type. NOT checked here:
    the actual FilterNode/query-language grammar inside `filters`/`query`
    (field names, ops, values) - that only happens once, at search time, in
    `auditor` (django_app has no import path to auditor's AST module and
    isn't meant to grow one just for this). This layer exists to catch
    structural mistakes - a bare string, an unrelated/misspelled key, a
    wrong-typed value - immediately, not a preset that "looks like" a
    filter but 400s every time it's actually used to search.
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError(
            "filter_body must be a JSON object matching the search request body "
            "shape (e.g. {'filters': {...}} or {'query': '...'}), not a bare value."
        )

    unknown_keys = set(value) - set(_FILTER_BODY_KEY_TYPES)
    if unknown_keys:
        raise serializers.ValidationError(
            f"filter_body has unrecognized key(s): {', '.join(sorted(unknown_keys))}. "
            f"Allowed keys: {', '.join(sorted(_FILTER_BODY_KEY_TYPES))}."
        )

    for key, expected_type in _FILTER_BODY_KEY_TYPES.items():
        if key in value and not isinstance(value[key], expected_type):
            raise serializers.ValidationError(
                f"filter_body.{key} must be a {expected_type.__name__}, "
                f"got {type(value[key]).__name__}."
            )

    if value.get("filters") is not None and value.get("query") is not None:
        raise serializers.ValidationError(
            "filter_body cannot set both 'filters' and 'query' - they are "
            "mutually exclusive, same as the search request body."
        )
    return value


class AuditFilterPresetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditFilterPreset
        fields = ["id", "name", "filter_body", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_filter_body(self, value):
        return _validate_filter_body(value)

    def validate(self, attrs):
        name = attrs.get("name")
        if name is None:  # partial update not touching the name
            return attrs

        request = self.context["request"]
        org_id = resolve_active_org_id(request)
        qs = AuditFilterPreset.objects.filter(
            org_id=org_id, created_by=request.user, name=name
        )
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"name": "You already have a preset with this name."}
            )
        return attrs


class AuditFilterPresetCopySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False, allow_blank=False)


class AuditFilterPresetImportFileSerializer(serializers.Serializer):
    """The actual upload - a `.json` file, exactly what `export`/`export_all`
    produce, attached as multipart/form-data (matches the Agent/Crew/Graph
    import convention - see ImportRequestSerializer) rather than pasted as
    a raw JSON request body. Its parsed contents are then validated by
    AuditFilterPresetImportSerializer below."""

    file = serializers.FileField()


class AuditFilterPresetImportItemSerializer(serializers.Serializer):
    """One preset's portable shape - matches the export shape exactly
    (no id/org/created_by/timestamps - those are server-owned identity,
    never taken from an imported file)."""

    name = serializers.CharField(max_length=150)
    filter_body = serializers.JSONField()

    def validate_filter_body(self, value):
        return _validate_filter_body(value)


class AuditFilterPresetImportSerializer(serializers.Serializer):
    """Accepts either one preset object or {"presets": [...]} - see
    AuditFilterPresetViewSet.import_presets."""

    name = serializers.CharField(max_length=150, required=False)
    filter_body = serializers.JSONField(required=False)
    presets = AuditFilterPresetImportItemSerializer(many=True, required=False)

    def validate_filter_body(self, value):
        return _validate_filter_body(value)

    def validate(self, attrs):
        has_single = "name" in attrs and "filter_body" in attrs
        has_batch = "presets" in attrs
        if has_single == has_batch:
            raise serializers.ValidationError(
                "Provide either a single {name, filter_body} object or a {presets: [...]} batch, not both/neither."
            )
        return attrs

    def to_items(self) -> list[dict]:
        data = self.validated_data
        if "presets" in data:
            return data["presets"]
        return [{"name": data["name"], "filter_body": data["filter_body"]}]
