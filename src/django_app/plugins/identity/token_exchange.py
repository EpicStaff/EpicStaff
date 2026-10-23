"""The plugin token exchange: an authorization code and its PKCE verifier for a login token."""

import base64
import hashlib
import hmac
from dataclasses import dataclass

from django.contrib.auth import get_user_model

from plugins.access.plugin_access import (
    PersonPluginAccess,
    loginable_plugin,
    resolve_person_plugin_access,
)
from plugins.audit import log_login_access_denied, log_login_token_issued
from plugins.exceptions import InvalidGrantError, PluginAccessDeniedError, PluginNotFoundError
from plugins.identity.authorization_codes import (
    AuthorizationCodeRecord,
    PluginAuthorizationCodeService,
)
from plugins.identity.plugin_login_tokens import (
    IssuedPluginLoginToken,
    issue_plugin_login_token,
    password_fingerprint,
)
from plugins.models import Plugin

ACCESS_LOST = "not_eligible"


@dataclass(frozen=True)
class PluginLogin:
    """A token just issued, with the person's access and the plugin it is for."""

    token: IssuedPluginLoginToken
    access: PersonPluginAccess
    plugin: Plugin


class PluginTokenExchangeService:
    def __init__(self, codes: PluginAuthorizationCodeService | None = None):
        self._codes = codes or PluginAuthorizationCodeService()

    def exchange(self, *, code: str, code_verifier: str, origin: str | None) -> PluginLogin:
        """Consume `code` and return a login token for the person and organization it names.

        The code is consumed before anything is compared, so a wrong verifier or `Origin`
        burns it. A code is bound to the password the person had when it was issued, as every
        EpicStaff session is. The person's access is resolved again, as it may have changed
        since the code was issued, and must still be through the same grant.

        Raises:
            InvalidGrantError: The code is unknown, expired or used, the request's `Origin`
                is not the plugin frame origin it was issued for, the verifier does not
                match its challenge, or the person's password changed since.
            PluginAccessDeniedError: The person may no longer use the plugin there.
        """
        record = self._codes.consume(code)
        if record is None:
            raise InvalidGrantError()
        if origin != record.origin or not _verifier_matches(code_verifier, record.code_challenge):
            raise InvalidGrantError()
        user = get_user_model().objects.filter(pk=record.user_id).first()
        if user is not None and not hmac.compare_digest(
            password_fingerprint(user.password), record.password_fingerprint
        ):
            raise InvalidGrantError()
        login = _current_access(record, user)
        if login is None:
            log_login_access_denied(
                user_id=record.user_id, identifier=record.plugin, reason=ACCESS_LOST
            )
            raise PluginAccessDeniedError()
        access, plugin = login
        token = issue_plugin_login_token(
            user=access.user,
            org_id=access.organization.pk,
            grant_id=access.grant.pk,
            identifier=plugin.identifier,
        )
        log_login_token_issued(
            user_id=access.user.pk,
            org_id=access.organization.pk,
            identifier=plugin.identifier,
            jti=token.jti,
        )
        return PluginLogin(token=token, access=access, plugin=plugin)


def _verifier_matches(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(challenge, code_challenge)


def _current_access(
    record: AuthorizationCodeRecord, user
) -> tuple[PersonPluginAccess, Plugin] | None:
    if user is None:
        return None
    try:
        plugin = loginable_plugin(record.plugin)
    except PluginNotFoundError:
        return None
    access = resolve_person_plugin_access(user, record.org_id, plugin)
    if access is None or access.grant.pk != record.grant_id:
        return None
    return access, plugin
