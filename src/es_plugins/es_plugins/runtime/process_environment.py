"""The command and environment of a plugin process: exactly these, nothing inherited.

No secret is ever in the command line: every process on the node can read every other's
`/proc/<pid>/cmdline`. The plugin's setting secrets reach it only through its runtime file. The
platform's credentials for it, its database URL and its egress proxy URL, are in its
environment, which, like the runtime file, only its own UID can read.

Every backend gets the proxy variables, so a call to an undeclared host is a clear 403 from the
proxy rather than a failed DNS lookup. `NO_PROXY` keeps EpicStaff's internal API and loopback
direct.
"""

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

from epicstaff_plugin.contracts.runtime import (
    DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE,
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    LOOPBACK_NO_PROXY_HOSTS,
    NO_PROXY_ENVIRONMENT_VARIABLES,
    PROXY_ENVIRONMENT_VARIABLES,
    RuntimeFile,
)
from src.shared.models.plugin_nodes import DesiredDatabase, DesiredPlacement

from es_plugins.egress.policy_writer import EGRESS_PROXY_ADDRESS
from es_plugins.layout import NodeLayout

SERVE_MODULE = "epicstaff_plugin.serve"
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


@dataclass(frozen=True)
class PlatformCredentials:
    """The platform's credentials a plugin process is started with."""

    egress_password: str = field(repr=False)
    database_password: str | None = field(default=None, repr=False)
    """The app role's password; given exactly when the placement has a database."""


def plugin_command(venv: Path) -> list[str]:
    """`<venv>/bin/python -I -m epicstaff_plugin.serve`: isolated, no script directory on the path."""
    return [str(venv / "bin" / "python"), "-I", "-m", SERVE_MODULE]


def plugin_environment(
    layout: NodeLayout,
    placement: DesiredPlacement,
    venv: Path,
    runtime_file: RuntimeFile,
    credentials: PlatformCredentials,
) -> dict[str, str]:
    # EPICSTAFF_PLUGIN_LISTEN_FD is not set here: the launcher adds it at spawn, naming the fd
    # the agent's listening socket lands on. PORT stays, for the plugin's information.
    identifier = placement.plugin_identifier
    home = layout.plugin_home(identifier)
    environment = {
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
    proxy_user = quote(identifier, safe="")
    proxy_password = quote(credentials.egress_password, safe="")
    proxy_url = f"http://{proxy_user}:{proxy_password}@{EGRESS_PROXY_ADDRESS}"
    environment.update(dict.fromkeys(PROXY_ENVIRONMENT_VARIABLES, proxy_url))
    direct_hosts = ",".join(
        [urlsplit(runtime_file.epicstaff_api_url).hostname, *LOOPBACK_NO_PROXY_HOSTS]
    )
    environment.update(dict.fromkeys(NO_PROXY_ENVIRONMENT_VARIABLES, direct_hosts))
    if placement.database is not None:
        if credentials.database_password is None:
            raise ValueError("a placement with a database is started with its app password")
        environment[DATABASE_URL_ENVIRONMENT_VARIABLE] = database_url(
            identifier, placement.database, credentials.database_password
        )
        environment[DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE] = str(
            placement.database.connection_limit
        )
    return environment


def database_url(identifier: str, database: DesiredDatabase, app_password: str) -> str:
    """`postgresql://<app role>:<password>@<host>:<port>/<database>?application_name=<id>`."""
    server = database.server
    return (
        f"postgresql://{quote(database.app_role, safe='')}:{quote(app_password, safe='')}"
        f"@{server.host}:{server.port}/{quote(database.database_name, safe='')}"
        f"?application_name={quote(identifier, safe='')}"
    )
