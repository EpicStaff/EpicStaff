"""The plugin authorize step: where EpicStaff sends the browser after it reads the session.

Every redirect goes either to the plugin's own callback page (`frame_origin(plugin)` plus a
fixed path, with the result in the fragment) or to one of EpicStaff's own pages (login, the
organization chooser). No target is ever taken from the request.
"""

import time
from dataclasses import dataclass
from urllib.parse import urlencode

from plugins.access.plugin_access import (
    PersonPluginAccess,
    eligible_accesses,
    resolve_person_plugin_access,
)
from plugins.audit import log_login_access_denied
from plugins.identity.authorization_codes import (
    AuthorizationCodeRecord,
    PluginAuthorizationCodeService,
)
from plugins.identity.login_protocol import (
    ACCESS_DENIED,
    AUTHORIZE_PATH,
    CALLBACK_PATH,
    CHOOSE_ORG_PATH,
    INTERACTION_REQUIRED,
    LOGIN_CONTINUE_PATH,
    LOGIN_REQUIRED,
    PROMPT_NONE,
    SILENT_CALLBACK_PATH,
)
from plugins.identity.plugin_login_tokens import password_fingerprint
from plugins.models import Plugin
from plugins.origins import PluginOrigins

ORG_NOT_ELIGIBLE = "org_not_eligible"
NO_ELIGIBLE_ORG = "no_eligible_org"


@dataclass(frozen=True)
class AuthorizeQuery:
    """A validated authorize request (`plugins.serializers.login.parse_authorize_query`)."""

    plugin: str
    state: str
    code_challenge: str
    code_challenge_method: str
    org: int | None = None
    prompt: str | None = None

    @property
    def silent(self) -> bool:
        return self.prompt == PROMPT_NONE

    def continue_path(self) -> str:
        """The authorize request to resume after login or the chooser, rebuilt from the
        validated values. It never asks for a silent answer, as those pages are interactive."""
        parameters = [
            ("plugin", self.plugin),
            ("state", self.state),
            ("code_challenge", self.code_challenge),
            ("code_challenge_method", self.code_challenge_method),
        ]
        if self.org is not None:
            parameters.append(("org", str(self.org)))
        return f"{AUTHORIZE_PATH}?{urlencode(parameters)}"


class PluginAuthorizationService:
    """Decides the answer to one authorize request."""

    def __init__(self, codes: PluginAuthorizationCodeService | None = None):
        self._codes = codes or PluginAuthorizationCodeService()

    def redirect_target(self, query: AuthorizeQuery, plugin: Plugin, user) -> str:
        """Return the URL to send the browser to.

        `user` is the person the refresh cookie signs in, or None. Without a session the
        browser goes to EpicStaff's login (or, for a silent request, back with
        `login_required`). With one, the organization is the one named, else the only one the
        person may use the plugin in; with several, EpicStaff's chooser (or
        `interaction_required`). A person who may use it nowhere asked gets `access_denied`.
        Otherwise a code is issued for the plugin's callback.
        """
        origins = PluginOrigins()
        if user is None:
            if query.silent:
                return _callback_url(origins, query, error=LOGIN_REQUIRED)
            return _epicstaff_page_url(origins, LOGIN_CONTINUE_PATH, query)
        if query.org is not None:
            access = resolve_person_plugin_access(user, query.org, plugin)
            if access is None:
                return _denied(origins, query, user, ORG_NOT_ELIGIBLE)
        else:
            accesses = eligible_accesses(user, plugin)
            if not accesses:
                return _denied(origins, query, user, NO_ELIGIBLE_ORG)
            if len(accesses) > 1:
                if query.silent:
                    return _callback_url(origins, query, error=INTERACTION_REQUIRED)
                return _epicstaff_page_url(origins, CHOOSE_ORG_PATH, query)
            access = accesses[0]
        return _callback_url(origins, query, code=self._issue_code(origins, query, access))

    def _issue_code(
        self, origins: PluginOrigins, query: AuthorizeQuery, access: PersonPluginAccess
    ) -> str:
        return self._codes.issue(
            AuthorizationCodeRecord(
                user_id=access.user.pk,
                org_id=access.organization.pk,
                grant_id=access.grant.pk,
                plugin=query.plugin,
                code_challenge=query.code_challenge,
                origin=origins.frame_origin(query.plugin),
                password_fingerprint=password_fingerprint(access.user.password),
                issued_at=int(time.time()),
            )
        )


def _denied(origins: PluginOrigins, query: AuthorizeQuery, user, reason: str) -> str:
    log_login_access_denied(user_id=user.pk, identifier=query.plugin, reason=reason)
    return _callback_url(origins, query, error=ACCESS_DENIED)


def _callback_url(origins: PluginOrigins, query: AuthorizeQuery, **result: str) -> str:
    path = SILENT_CALLBACK_PATH if query.silent else CALLBACK_PATH
    fragment = urlencode({**result, "state": query.state})
    return f"{origins.frame_origin(query.plugin)}{path}#{fragment}"


def _epicstaff_page_url(origins: PluginOrigins, path: str, query: AuthorizeQuery) -> str:
    return f"{origins.epicstaff_origin}{path}?{urlencode({'continue': query.continue_path()})}"
