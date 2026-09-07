from rest_framework import serializers

from tables.serializers.permission_serializers import RoleResponseSerializer


class RolePermissionInputSerializer(serializers.Serializer):
    resource_type = serializers.CharField()
    actions = serializers.ListField(child=serializers.CharField(), allow_empty=True)


class RoleWriteSerializer(serializers.Serializer):
    """Create/update body. `org_id` is required on create, absent on
    update (the role's org is derived from the row). Validation of names,
    reserved words, and applicable actions is performed by
    RoleValidationService, not here — this serializer is the Swagger shape
    and a light structural contract."""

    org_id = serializers.IntegerField(required=False)
    name = serializers.CharField(required=False)
    description = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    permissions = RolePermissionInputSerializer(many=True, required=False)


class RoleListResponseSerializer(serializers.Serializer):
    """Envelope returned by GET /api/admin/roles/ — the paginated custom
    roles (`results`) plus the always-present built-in templates."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = RoleResponseSerializer(many=True)
    built_in_roles = RoleResponseSerializer(many=True)


class RoleDeleteResultSerializer(serializers.Serializer):
    """Response of a real DELETE /api/admin/roles/{id}/."""

    reassigned_count = serializers.IntegerField()


class AffectedRoleUserSerializer(serializers.Serializer):
    """A member who would be reassigned to the built-in Member role if the
    role were deleted."""

    user_id = serializers.IntegerField()
    email = serializers.EmailField()
    display_name = serializers.CharField(allow_null=True)


class RoleDeletePreviewSerializer(serializers.Serializer):
    """Response of DELETE /api/admin/roles/{id}/?dry_run=true (no mutation)."""

    role_id = serializers.IntegerField()
    assigned_count = serializers.IntegerField()
    affected_users = AffectedRoleUserSerializer(many=True)
