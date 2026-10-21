"""The command and environment of a plugin process: exactly these, nothing inherited.

No secret is ever in the command line: every process on the node can read every other's
`/proc/<pid>/cmdline`. Secrets reach the plugin only through its runtime file, which only
its UID can read.
"""

from pathlib import Path

from epicstaff_plugin.contracts.runtime import RuntimeFile
from src.shared.models.plugin_nodes import DesiredPlacement

from es_plugins.layout import NodeLayout

SERVE_MODULE = "epicstaff_plugin.serve"
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


def plugin_command(venv: Path) -> list[str]:
    """`<venv>/bin/python -I -m epicstaff_plugin.serve`: isolated, no script directory on the path."""
    return [str(venv / "bin" / "python"), "-I", "-m", SERVE_MODULE]


def plugin_environment(
    layout: NodeLayout, placement: DesiredPlacement, venv: Path, runtime_file: RuntimeFile
) -> dict[str, str]:
    # EPICSTAFF_PLUGIN_LISTEN_FD is not set here: the launcher adds it at spawn, naming the fd
    # the agent's listening socket lands on. PORT stays, for the plugin's information.
    identifier = placement.plugin_identifier
    home = layout.plugin_home(identifier)
    return {
        "PORT": str(placement.runtime.port),
        # No /etc/passwd entry exists for a plugin UID; these make getpass.getuser() work.
        "USER": identifier,
        "LOGNAME": identifier,
        "HOME": str(home),
        "TMPDIR": str(layout.plugin_temporary_directory(identifier)),
        "PATH": f"{venv / 'bin'}:{SYSTEM_PATH}",
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "EPICSTAFF_PLUGIN_IDENTIFIER": identifier,
        "EPICSTAFF_PLUGIN_VERSION": placement.package.version,
        "EPICSTAFF_PLUGIN_ENTRYPOINT": placement.runtime.entrypoint,
        "EPICSTAFF_PLUGIN_RUNTIME_FILE": str(layout.runtime_file(identifier)),
        "EPICSTAFF_API_URL": runtime_file.epicstaff_api_url,
        "EPICSTAFF_PUBLIC_URL": runtime_file.epicstaff_public_url,
        "EPICSTAFF_PLUGIN_PUBLIC_URL": runtime_file.public_url,
    }
