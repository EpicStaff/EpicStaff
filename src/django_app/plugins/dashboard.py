from plugins.models import GrantState, PluginGrant


def count_installed_plugins(org_id: int) -> int:
    return PluginGrant.objects.filter(
        org_id=org_id, state__in=(GrantState.ACTIVE, GrantState.UPGRADING)
    ).count()
