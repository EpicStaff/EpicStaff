from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from loguru import logger
from tables.models import (
    GraphOrganization,
    GraphOrganizationUser,
    OrganizationUser,
)


def sync_variables(
    instance,
    field_name,
    display_name,
    object_type="organization",
    current_variables=None,
):
    """
    Sync a JSON field on an instance with current_variables (handles nested structures):
    - Remove keys that are not present in current_variables
    - Add key/value from current_variables if missing in the instance
    - Keep existing values for keys that exist in both (recursively for nested dicts)
    """
    if current_variables is None:
        return

    original_vars = getattr(instance, field_name, {}) or {}

    updated_vars, _, _ = _sync_nested_dict(original_vars, current_variables)

    if updated_vars != original_vars:
        setattr(instance, field_name, updated_vars)
        instance.save(update_fields=[field_name])
        logger.info(f"Variables synced for {object_type} {display_name}.")


def _sync_nested_dict(original, current, path=""):
    """
    Recursively sync nested dictionaries.
    Returns: (updated_dict, removed_paths, added_paths)
    """
    updated = {}
    removed_paths = []
    added_paths = []

    for key in current.keys():
        current_path = f"{path}.{key}" if path else key

        if key in original:
            original_value = original[key]
            current_value = current[key]

            if isinstance(original_value, dict) and isinstance(current_value, dict):
                nested_result, nested_removed, nested_added = _sync_nested_dict(
                    original_value, current_value, current_path
                )
                updated[key] = nested_result
                removed_paths.extend(nested_removed)
                added_paths.extend(nested_added)
            else:
                updated[key] = original_value
        else:
            updated[key] = current[key]
            added_paths.append(current_path)

    for key in original.keys():
        if key not in current:
            removed_path = f"{path}.{key}" if path else key
            removed_paths.append(removed_path)

    return updated, removed_paths, added_paths


@receiver(post_save, sender=GraphOrganization)
def update_organization_objects(sender, instance, created, **kwargs):
    """
    Updates persistent_variables for users after user_variables was changed.
    """
    if created:
        return

    current_variables = instance.user_variables
    graph_users = GraphOrganizationUser.objects.filter(
        user__organization=instance.organization
    )

    for graph_user in graph_users:
        sync_variables(
            graph_user,
            "persistent_variables",
            graph_user.user.name,
            "user",
            current_variables,
        )


@receiver(post_delete, sender=GraphOrganization)
def delete_related_graph_organization_users(sender, instance, **kwargs):
    """
    Delete all GraphOrganizationUser records with the same organization
    when a GraphOrganization is deleted.
    """
    org_users = OrganizationUser.objects.filter(organization=instance.organization)

    GraphOrganizationUser.objects.filter(
        graph=instance.graph, user__in=org_users
    ).delete()
