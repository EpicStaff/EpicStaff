from dataclasses import dataclass, field

from src.shared.envtools import Env, EnvironmentNotFoundError

from es_plugins.uid_range import UidRange

MINIMUM_NODE_KEY_LENGTH = 32
MINIMUM_DATABASE_ADMIN_PASSWORD_LENGTH = 32


class AgentSettingsError(Exception):
    """A variable the agent needs is missing or invalid; the message names it, never its value."""


@dataclass(frozen=True)
class AgentSettings:
    node_name: str
    node_key: str = field(repr=False)
    api_url: str
    uid_range: UidRange
    disk_megabytes_per_plugin: int
    """`ES_PLUGINS_DISK_MB_PER_PLUGIN`: the disk a plugin's HOME may take, for every plugin."""

    files_per_plugin: int
    """`ES_PLUGINS_FILES_PER_PLUGIN`: the files (inodes) a plugin's HOME may hold."""

    database_admin_password: str = field(repr=False)
    """`PLUGINS_DB_ADMIN_PASSWORD`: `plugins_admin`'s password on plugins_db."""

    @classmethod
    def from_environment(cls, env: Env | None = None) -> "AgentSettings":
        """Read the node's variables (the launcher passes them on from the container).

        Raises:
            AgentSettingsError: A variable is missing, the node key or the database admin
                password is `none` or short, or a disk cap is not a whole number above 0.
        """
        env = env or Env()
        try:
            node_name = env.str("PLUGINS_NODE_NAME")
            node_key = env.str("PLUGINS_NODE_KEY")
            api_url = env.str("PLUGINS_INTERNAL_API_URL")
            uid_range = UidRange.parse(env.str("PLUGINS_NODE_UID_RANGE") or "")
            disk_megabytes = env.int("ES_PLUGINS_DISK_MB_PER_PLUGIN")
            files = env.int("ES_PLUGINS_FILES_PER_PLUGIN")
            database_admin_password = env.str("PLUGINS_DB_ADMIN_PASSWORD")
        except (EnvironmentNotFoundError, ValueError) as error:
            raise AgentSettingsError(str(error)) from None
        for name, value in (
            ("ES_PLUGINS_DISK_MB_PER_PLUGIN", disk_megabytes),
            ("ES_PLUGINS_FILES_PER_PLUGIN", files),
        ):
            if value is None or value < 1:
                raise AgentSettingsError(f"{name} must be a whole number above 0, not {value}")
        if not node_key or len(node_key) < MINIMUM_NODE_KEY_LENGTH:
            raise AgentSettingsError(
                "PLUGINS_NODE_KEY must be set to the key django_app knows, at least 32 characters "
                "(generate one with: openssl rand -hex 32)"
            )
        # `none`, the variable's default, is shorter than the minimum too.
        if (
            not database_admin_password
            or len(database_admin_password) < MINIMUM_DATABASE_ADMIN_PASSWORD_LENGTH
        ):
            raise AgentSettingsError(
                "PLUGINS_DB_ADMIN_PASSWORD must be set to the password plugins_db was first "
                "started with, at least 32 characters (generate one with: openssl rand -hex 32)"
            )
        if not node_name or not api_url:
            raise AgentSettingsError("PLUGINS_NODE_NAME and PLUGINS_INTERNAL_API_URL must be set")
        if not api_url.endswith("/"):
            api_url += "/"
        return cls(
            node_name=node_name,
            node_key=node_key,
            api_url=api_url,
            uid_range=uid_range,
            disk_megabytes_per_plugin=disk_megabytes,
            files_per_plugin=files,
            database_admin_password=database_admin_password,
        )
