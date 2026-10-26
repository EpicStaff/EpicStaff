from epicstaff_plugin.problems import Problem
from rest_framework import serializers

from plugins.development.development_host import DevelopmentHost
from plugins.models.development import MAX_DEVELOPMENT_PORT, MIN_DEVELOPMENT_PORT
from plugins.serializers.common import UserRefSerializer


class PluginDevelopmentPortsSerializer(serializers.Serializer):
    backend_port = serializers.IntegerField(
        allow_null=True,
        help_text="The author's backend, reached at host.docker.internal:<port>.",
    )
    spa_port = serializers.IntegerField(
        allow_null=True, help_text="The author's frontend development server."
    )


class PluginDevelopmentTargetSerializer(PluginDevelopmentPortsSerializer):
    updated_at = serializers.DateTimeField()
    updated_by = UserRefSerializer(allow_null=True)


class PluginDevelopmentSerializer(serializers.Serializer):
    """A plugin's Development tab; serializes a `PluginDevelopmentState`."""

    development_mode = serializers.BooleanField(
        help_text="PLUGINS_DEV_MODE as django_app reads it now."
    )
    host = serializers.ChoiceField(choices=[DevelopmentHost.NAME])
    host_address = serializers.CharField(
        allow_null=True,
        help_text=(
            "The IPv4 address the host resolves to in django_app now; null when it does not "
            "resolve or development mode is off."
        ),
    )
    api_url = serializers.CharField(
        allow_null=True,
        help_text=(
            "Where a development backend reaches EpicStaff's API; null when development mode "
            "is off."
        ),
    )
    can_use_backend = serializers.BooleanField(help_text="The current package has a backend.")
    can_use_spa = serializers.BooleanField(help_text="The current package has a page.")
    target = PluginDevelopmentTargetSerializer(
        allow_null=True,
        help_text="The stored target, shown also while development mode is off (it is then inert).",
    )
    runtime_file_issued_at = serializers.DateTimeField(
        allow_null=True,
        help_text=(
            "When the development keys that work now were issued; null when none works (never "
            "downloaded, development stopped, or every organization suspended since)."
        ),
    )


_PORT_RANGE = f"must be a whole number from {MIN_DEVELOPMENT_PORT} to {MAX_DEVELOPMENT_PORT}"


def _port_field() -> serializers.IntegerField:
    return serializers.IntegerField(
        min_value=MIN_DEVELOPMENT_PORT,
        max_value=MAX_DEVELOPMENT_PORT,
        allow_null=True,
        required=False,
        default=None,
        error_messages={
            "invalid": _PORT_RANGE,
            "min_value": _PORT_RANGE,
            "max_value": _PORT_RANGE,
            "max_string_length": _PORT_RANGE,
        },
    )


class PluginDevelopmentUpdateSerializer(serializers.Serializer):
    """The ports a SuperAdmin sets; at least one of them.

    Needs `api_port`, `can_use_backend` and `can_use_spa` in its context: a port never equals
    the development API listener's, and only the parts the package has can be routed. No
    message repeats a submitted value.
    """

    backend_port = _port_field()
    spa_port = _port_field()

    def validate_backend_port(self, port: int | None) -> int | None:
        if port is not None and not self.context["can_use_backend"]:
            raise serializers.ValidationError("cannot be set: this plugin has no backend")
        return self._not_the_api_port(port)

    def validate_spa_port(self, port: int | None) -> int | None:
        if port is not None and not self.context["can_use_spa"]:
            raise serializers.ValidationError("cannot be set: this plugin has no page")
        return self._not_the_api_port(port)

    def validate(self, attrs: dict) -> dict:
        if attrs["backend_port"] is None and attrs["spa_port"] is None:
            raise serializers.ValidationError(
                "needs a backend port or a frontend dev server port; to route nothing, stop "
                "development instead"
            )
        return attrs

    def problems(self) -> list[Problem]:
        """The errors of a failed `is_valid()`, as `{loc, message}` problems."""
        return [
            Problem(str(location), str(message))
            for location, messages in self.errors.items()
            for message in messages
        ]

    def _not_the_api_port(self, port: int | None) -> int | None:
        if port is not None and port == self.context["api_port"]:
            raise serializers.ValidationError(
                "is the development API port (PLUGINS_DEV_API_PORT); use another port"
            )
        return port
