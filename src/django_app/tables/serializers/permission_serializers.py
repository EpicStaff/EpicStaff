from rest_framework import serializers

from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.permission_catalog import applicable_actions_for
from tables.services.rbac.utils.permission_bitmask import bitmask_to_actions


class CatalogActionSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    bit = serializers.IntegerField()


class CatalogResourceTypeSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    group = serializers.CharField()
    description = serializers.CharField()
    applicable_actions = serializers.ListField(child=serializers.CharField())


class CatalogResponseSerializer(serializers.Serializer):
    actions = CatalogActionSerializer(many=True)
    resource_types = CatalogResourceTypeSerializer(many=True)


class RolePermissionEntrySerializer(serializers.Serializer):
    resource_type = serializers.CharField()
    actions = serializers.ListField(child=serializers.CharField())


class RoleResponseSerializer(serializers.Serializer):
    """Renders Role with attached `_perm_rows` and `_assigned_count`
    (set by RoleManagementService). Filters zero-permission rows
    from the response so the FE doesn't see noise."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True)
    is_built_in = serializers.BooleanField()
    scope = serializers.CharField()
    org_id = serializers.IntegerField(allow_null=True)
    org = serializers.DictField(allow_null=True)
    assigned_count = serializers.IntegerField()
    permissions = RolePermissionEntrySerializer(many=True)

    def to_representation(self, instance):
        return {
            "id": instance.id,
            "name": instance.name,
            "description": instance.description,
            "is_built_in": instance.is_built_in,
            "scope": self._derive_scope(instance),
            "org_id": getattr(instance, "_effective_org_id", instance.org_id),
            "org": self._org_obj(instance),
            "assigned_count": getattr(instance, "_assigned_count", 0),
            "permissions": [
                {
                    "resource_type": row.resource_type,
                    "actions": bitmask_to_actions(
                        row.permissions,
                        applicable=applicable_actions_for(row.resource_type),
                    ),
                }
                for row in getattr(instance, "_perm_rows", [])
                if row.permissions != 0
            ],
        }

    @staticmethod
    def _org_obj(role):
        if role.org_id is None:
            return None
        return {"id": role.org_id, "name": role.org.name}

    @staticmethod
    def _derive_scope(role):
        if (
            role.is_built_in
            and role.org_id is None
            and role.name == BuiltInRole.SUPERADMIN
        ):
            return "global"
        return "org"


class PermissionsMeResponseSerializer(serializers.Serializer):
    """Permissive shape — `permissions` is either "*" (superadmin) or
    a dict[resource_type, list[action_code]]. drf-spectacular renders
    a union; runtime is duck-typed."""

    org_id = serializers.IntegerField()
    is_superadmin = serializers.BooleanField()
    role = serializers.DictField(allow_null=True)
    permissions = serializers.JSONField()


class MyOrgsPermissionsResponseSerializer(serializers.Serializer):
    """Multi-org capability response. `permissions` per org is
    {resource_type: [action_code]}; the top-level `permissions` is "*"
    for superadmin (in which case `orgs` is omitted). Duck-typed;
    drf-spectacular renders the union permissively."""

    is_superadmin = serializers.BooleanField()
    permissions = serializers.JSONField(required=False)
    orgs = serializers.ListField(child=serializers.DictField(), required=False)
