"""Where the plugin node keeps everything, shared by the launcher and the agent.

```
/var/lib/es_plugins/                    0755 root:root     the es_plugins_data volume
    agent/                              0750 10000:0       agent home: downloads/, unpack/, tmp/
    data/                               0711 root:root
        <id>/                           0700 uid:uid       the plugin's HOME
            tmp/                        0700 uid:uid       the plugin's TMPDIR
    plugins/                            0711 root:root
        <id>/                           0750 root:uid
            <version>/backend/src/      0755 root:root     the plugin's code, read-only to it
    venvs/                              0711 root:root
        <id>/                           0750 10000:uid
            <version>/                                     built by the agent
    logs/                               0700 10000:10000
        <id>/current.log
    backups/                            0700 10000:10000   no plugin UID may enter it
        <id>/                           0700 10000:10000
            <name>.dump, <name>.json    0600 10000:10000   a backup of the plugin's database
/run/es_plugins/                        0711 root:root
    agent.heartbeat                     0644 10000:10000   the container's health check
    <id>/                               0711 root:root
        runtime.json                    0400 uid:uid
/run/es_launcher/                       0750 root:10000
    launcher.sock                       0660 root:10000
/var/lib/es_plugins_egress/             0710 root:10000    made by the image
    policy/                             0755 10000:10000   the plugin_egress_policy volume
        passwords, hosts.json           0644 10000:10000   the egress proxy's policy
```

Each plugin's gid equals its uid. `agent/` belongs to group 0 so the launcher, which has no
`CAP_DAC_OVERRIDE`, can read what the agent unpacked there while no plugin can. Plugin UIDs
cannot pass through `/var/lib/es_plugins_egress/`, so no plugin reads another's allow-list or
password hash; plugins_egress mounts the same volume read-only.
"""

import re
from dataclasses import dataclass
from pathlib import Path

AGENT_UID = 10000
AGENT_GID = 10000

PLUGIN_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")
# A package version as a single path segment: SemVer characters only, never "." or "..".
VERSION_SEGMENT_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")

RUNTIME_FILE_NAME = "runtime.json"
HEARTBEAT_FILE_NAME = "agent.heartbeat"
LAUNCHER_SOCKET_NAME = "launcher.sock"


def check_plugin_identifier(identifier: str) -> str:
    """Return the identifier, or raise `ValueError` if it is not a plugin identifier."""
    if not PLUGIN_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"{identifier!r} is not a plugin identifier")
    return identifier


def check_version_segment(version: str) -> str:
    """Return the version, or raise `ValueError` if it cannot be one path segment."""
    if not VERSION_SEGMENT_PATTERN.fullmatch(version) or ".." in version:
        raise ValueError(f"{version!r} is not a package version usable as a directory name")
    return version


@dataclass(frozen=True)
class NodeLayout:
    """Every path of the node. Tests point the four roots at a temporary directory."""

    data_root: Path = Path("/var/lib/es_plugins")
    run_root: Path = Path("/run/es_plugins")
    launcher_socket_directory: Path = Path("/run/es_launcher")
    egress_policy_directory: Path = Path("/var/lib/es_plugins_egress/policy")

    @property
    def agent_directory(self) -> Path:
        return self.data_root / "agent"

    @property
    def downloads_directory(self) -> Path:
        return self.agent_directory / "downloads"

    @property
    def unpack_directory(self) -> Path:
        return self.agent_directory / "unpack"

    @property
    def agent_temporary_directory(self) -> Path:
        return self.agent_directory / "tmp"

    @property
    def plugin_data_root(self) -> Path:
        return self.data_root / "data"

    @property
    def plugins_root(self) -> Path:
        return self.data_root / "plugins"

    @property
    def venvs_root(self) -> Path:
        return self.data_root / "venvs"

    @property
    def logs_root(self) -> Path:
        return self.data_root / "logs"

    @property
    def backups_root(self) -> Path:
        return self.data_root / "backups"

    @property
    def heartbeat_file(self) -> Path:
        return self.run_root / HEARTBEAT_FILE_NAME

    @property
    def launcher_socket(self) -> Path:
        return self.launcher_socket_directory / LAUNCHER_SOCKET_NAME

    def plugin_home(self, identifier: str) -> Path:
        return self.plugin_data_root / check_plugin_identifier(identifier)

    def plugin_temporary_directory(self, identifier: str) -> Path:
        return self.plugin_home(identifier) / "tmp"

    def plugin_code_root(self, identifier: str) -> Path:
        return self.plugins_root / check_plugin_identifier(identifier)

    def plugin_code(self, identifier: str, version: str) -> Path:
        return self.plugin_code_root(identifier) / check_version_segment(version)

    def plugin_source(self, identifier: str, version: str) -> Path:
        """The directory a plugin's `.pth` file puts on its `sys.path`."""
        return self.plugin_code(identifier, version) / "backend" / "src"

    def plugin_venvs(self, identifier: str) -> Path:
        return self.venvs_root / check_plugin_identifier(identifier)

    def plugin_venv(self, identifier: str, version: str) -> Path:
        return self.plugin_venvs(identifier) / check_version_segment(version)

    def plugin_logs(self, identifier: str) -> Path:
        return self.logs_root / check_plugin_identifier(identifier)

    def plugin_backups(self, identifier: str) -> Path:
        return self.backups_root / check_plugin_identifier(identifier)

    def plugin_run_directory(self, identifier: str) -> Path:
        return self.run_root / check_plugin_identifier(identifier)

    def runtime_file(self, identifier: str) -> Path:
        return self.plugin_run_directory(identifier) / RUNTIME_FILE_NAME

    def unpacked_package(self, identifier: str, version: str) -> Path:
        """Where the agent unpacks a verified package's `backend/` before it is installed."""
        return (
            self.unpack_directory
            / check_plugin_identifier(identifier)
            / check_version_segment(version)
        )

    def unpacked_source(self, identifier: str, version: str) -> Path:
        return self.unpacked_package(identifier, version) / "backend" / "src"
