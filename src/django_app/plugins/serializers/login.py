"""Requests and responses of the plugin login endpoints.

Both requests are checked strictly: a parameter or key the protocol does not name, a repeated
parameter, or a value that does not match its whole pattern is refused, so a new parameter is
always a protocol change and never silently ignored. Submitted values are never echoed back.
"""

import re

from django.http import QueryDict
from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN
from epicstaff_plugin.problems import Problem
from rest_framework import serializers

from plugins.exceptions import InvalidAuthorizeRequestError, InvalidTokenRequestError
from plugins.identity.login_protocol import (
    AUTHORIZE_PARAMETERS,
    CODE_CHALLENGE_METHOD,
    CODE_CHALLENGE_PATTERN,
    CODE_PATTERN,
    CODE_VERIFIER_PATTERN,
    PROMPT_VALUES,
    STATE_PATTERN,
)
from plugins.identity.plugin_authorization import AuthorizeQuery
from plugins.serializers.admin import icon_url
from plugins.serializers.role_permissions import OrganizationRefSerializer

# Organization ids are 32-bit; anything else names no organization.
MAX_ORGANIZATION_ID = 2**31 - 1
_ORGANIZATION_ID_PATTERN = r"^[1-9][0-9]{0,9}$"
# An unknown parameter's name is named back in the error, cut to this length.
_MAX_NAMED_PARAMETER_LENGTH = 64

_AUTHORIZE_RULES = {
    "plugin": (IDENTIFIER_PATTERN, "must be a plugin identifier"),
    "state": (STATE_PATTERN, "must be 43 to 128 base64url characters"),
    "code_challenge": (CODE_CHALLENGE_PATTERN, "must be 43 base64url characters"),
    "code_challenge_method": (rf"^{CODE_CHALLENGE_METHOD}$", f"must be {CODE_CHALLENGE_METHOD}"),
    "org": (_ORGANIZATION_ID_PATTERN, "must be an organization id"),
    "prompt": (rf"^(?:{'|'.join(PROMPT_VALUES)})$", f"must be {' or '.join(PROMPT_VALUES)}"),
}
_REQUIRED_AUTHORIZE_PARAMETERS = ("plugin", "state", "code_challenge", "code_challenge_method")

_TOKEN_REQUEST_RULES = {
    "code": (CODE_PATTERN, "must be 43 base64url characters"),
    "code_verifier": (CODE_VERIFIER_PATTERN, "must be 43 to 128 PKCE verifier characters"),
}
TOKEN_BODY_LOC = "body"


def parse_authorize_query(query: QueryDict) -> AuthorizeQuery:
    """Validate the authorize request's query string.

    Raises:
        InvalidAuthorizeRequestError: A parameter is missing, repeated, unknown or malformed;
            each problem's `loc` is the parameter's name.
    """
    problems = []
    values: dict[str, str] = {}
    for name, given in query.lists():
        if name not in AUTHORIZE_PARAMETERS:
            problems.append(
                Problem(name[:_MAX_NAMED_PARAMETER_LENGTH], "is not a parameter of this request")
            )
        elif len(given) != 1:
            problems.append(Problem(name, "is given more than once"))
        else:
            values[name] = given[0]
    repeated = {problem.loc for problem in problems}
    problems.extend(
        Problem(name, "is required")
        for name in _REQUIRED_AUTHORIZE_PARAMETERS
        if name not in values and name not in repeated
    )
    for name, value in values.items():
        pattern, message = _AUTHORIZE_RULES[name]
        if re.fullmatch(pattern, value) is None or (
            name == "org" and int(value) > MAX_ORGANIZATION_ID
        ):
            problems.append(Problem(name, message))
    if problems:
        raise InvalidAuthorizeRequestError(problems)
    return AuthorizeQuery(
        plugin=values["plugin"],
        state=values["state"],
        code_challenge=values["code_challenge"],
        code_challenge_method=values["code_challenge_method"],
        org=int(values["org"]) if "org" in values else None,
        prompt=values.get("prompt"),
    )


def parse_token_request(body) -> tuple[str, str]:
    """Validate the token exchange's JSON body and return `(code, code_verifier)`.

    Raises:
        InvalidTokenRequestError: The body is not an object with exactly `code` and
            `code_verifier`, each a string matching its pattern.
    """
    if not isinstance(body, dict):
        raise InvalidTokenRequestError(
            [Problem(TOKEN_BODY_LOC, "must be an object with code and code_verifier")]
        )
    problems = [
        Problem(str(key)[:_MAX_NAMED_PARAMETER_LENGTH], "is not a field of this request")
        for key in body
        if key not in _TOKEN_REQUEST_RULES
    ]
    for name, (pattern, message) in _TOKEN_REQUEST_RULES.items():
        value = body.get(name)
        if value is None:
            problems.append(Problem(name, "is required"))
        elif not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            problems.append(Problem(name, message))
    if problems:
        raise InvalidTokenRequestError(problems)
    return body["code"], body["code_verifier"]


class PluginTokenResponseSerializer(serializers.Serializer):
    """A plugin login token and what it stands for (`plugins.identity.token_exchange.PluginLogin`)."""

    TOKEN_TYPE = "Bearer"

    access_token = serializers.CharField(source="token.token")
    token_type = serializers.SerializerMethodField()
    expires_in = serializers.IntegerField(source="token.expires_in")
    plugin = serializers.SerializerMethodField()
    org = OrganizationRefSerializer(source="access.organization")
    user = serializers.SerializerMethodField()
    plugin_permissions = serializers.ListField(
        source="access.actions", child=serializers.CharField()
    )

    def get_token_type(self, login) -> str:
        return self.TOKEN_TYPE

    def get_plugin(self, login) -> dict:
        return {
            "identifier": login.plugin.identifier,
            "version": login.plugin.current_package.version,
        }

    def get_user(self, login) -> dict:
        user = login.access.user
        return {"id": user.pk, "email": user.email, "name": user.effective_display_name}


class LoginPluginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    name = serializers.CharField()
    icon_url = serializers.SerializerMethodField()

    def get_icon_url(self, plugin) -> str | None:
        return icon_url(plugin)


class PluginLoginOrganizationsSerializer(serializers.Serializer):
    """The plugin and the caller's organizations they may open it in, for the chooser."""

    plugin = LoginPluginSerializer()
    organizations = OrganizationRefSerializer(many=True)
