"""How a plugin's backend authenticates to EpicStaff's API: `Authorization: PluginKey esp-…`.

One of DRF's default authentication classes, after a person's credentials. It answers only
for the `PluginKey` scheme and only while the plugin platform is on; any other request is
left to the other classes (`None`), so a JWT or an API key never reaches it. A `PluginKey`
request either authenticates or gets 401: it never falls through to anonymous.

The key works only through nginx's internal listener on the plugins network
(`internal_listener`), and only while its grant holds keys. The result is a
`PluginServiceAccountPrincipal` pinned to the grant's organization; `request.auth` is the key
row. A `X-EpicStaff-On-Behalf-Of` header names the person the call is for, checked here, so
`request.user.person` is set before any view runs.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from epicstaff_plugin.contracts.service_account_api import MAX_USER_ID
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission

from plugins.access.people_service import PluginPeopleService
from plugins.audit import log_service_account_refused
from plugins.configuration.limits import plugin_limits
from plugins.exceptions import InvalidOnBehalfOfError, ServiceAccountNotAuthenticatedError
from plugins.identity.internal_listener import came_through_internal_listener
from plugins.identity.principals import PluginServiceAccountPrincipal
from plugins.identity.service_account_keys import hash_service_account_key
from plugins.models import KEY_HOLDING_GRANT_STATES, PluginServiceAccount, PluginServiceAccountKey
from plugins.ownership.request_scope import scope_for_authentication

KEYWORD = "PluginKey"
ON_BEHALF_OF_META_KEY = "HTTP_X_EPICSTAFF_ON_BEHALF_OF"
LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)


class PluginServiceAccountAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if not settings.PLUGINS_ENABLED:
            return None
        scheme, _, raw_key = request.META.get("HTTP_AUTHORIZATION", "").partition(" ")
        if scheme != KEYWORD:
            return None
        if not came_through_internal_listener(request):
            _refuse(None, "outside_internal_listener")
        key = _key_by_hash(raw_key.strip())
        now = timezone.now()
        _assert_usable(key, now)
        _mark_used(key, now)
        grant = key.service_account.grant
        plugin = grant.plugin
        package = plugin.current_package
        principal = PluginServiceAccountPrincipal(
            service_account_id=key.service_account_id,
            grant_id=grant.pk,
            pinned_org_id=grant.org_id,
            plugin_identifier=plugin.identifier,
            plugin_name=plugin.name,
            package=package,
            requests_per_minute=plugin_limits(plugin, package.parsed_manifest).effective[
                "requests_per_minute"
            ],
        )
        on_behalf_of = _on_behalf_of_user_id(request)
        if on_behalf_of is not None:
            principal.person = PluginPeopleService().on_behalf_of(grant, on_behalf_of)
        scope_for_authentication().principal = principal
        return principal, key

    def authenticate_header(self, request) -> str:
        return KEYWORD


class IsPluginServiceAccount(BasePermission):
    """Admits only a request authenticated with a service-account key."""

    def has_permission(self, request, view) -> bool:
        return isinstance(request.auth, PluginServiceAccountKey)


class PluginKeyAuthScheme(OpenApiAuthenticationExtension):
    target_class = (
        "plugins.identity.service_account_authentication.PluginServiceAccountAuthentication"
    )
    name = "PluginKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "`PluginKey <key>`: a plugin backend's service-account key, accepted "
            "only through the plugins network.",
        }


def _key_by_hash(raw_key: str) -> PluginServiceAccountKey:
    key = (
        PluginServiceAccountKey.objects.select_related(
            "service_account__grant__org", "service_account__grant__plugin__current_package"
        )
        .defer("service_account__grant__plugin__current_package__icon_bytes")
        .filter(key_hash=hash_service_account_key(raw_key))
        .first()
        if raw_key
        else None
    )
    if key is None:
        _refuse(None, "unknown_key")
    return key


def _assert_usable(key: PluginServiceAccountKey, now) -> None:
    """The checks after the lookup, in a fixed order; the first that fails refuses the key."""
    account = key.service_account
    grant = account.grant
    identifier = grant.plugin.identifier
    if key.revoked_at is not None:
        _refuse(identifier, "revoked")
    if key.expires_at is not None and key.expires_at <= now:
        _refuse(identifier, "superseded")
    if account.revoked_at is not None:
        _refuse(identifier, "revoked")
    if grant.state not in KEY_HOLDING_GRANT_STATES:
        _refuse(identifier, "grant_state")
    if not grant.org.is_active:
        _refuse(identifier, "org_inactive")
    package = grant.plugin.current_package
    if package is None or package.parsed_manifest.backend is None:
        _refuse(identifier, "no_backend")


def _refuse(identifier: str | None, reason: str):
    log_service_account_refused(identifier=identifier, reason=reason)
    raise ServiceAccountNotAuthenticatedError()


def _mark_used(key: PluginServiceAccountKey, now) -> None:
    # On the account, not the key: a mint every few minutes would otherwise leave a trail of
    # keys to sort for the latest use. At most one write a minute, so a busy plugin does not
    # turn every call into one.
    account = key.service_account
    if account.last_used_at is not None and now - account.last_used_at < LAST_USED_WRITE_INTERVAL:
        return
    PluginServiceAccount.objects.filter(pk=account.pk).update(last_used_at=now)
    account.last_used_at = now


def _on_behalf_of_user_id(request) -> int | None:
    """The user id `X-EpicStaff-On-Behalf-Of` names, None without the header.

    Raises:
        InvalidOnBehalfOfError: The value is not a decimal positive integer below 2^63.
    """
    value = request.META.get(ON_BEHALF_OF_META_KEY)
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        raise InvalidOnBehalfOfError()
    user_id = int(value)
    if not 0 < user_id <= MAX_USER_ID:
        raise InvalidOnBehalfOfError()
    return user_id
