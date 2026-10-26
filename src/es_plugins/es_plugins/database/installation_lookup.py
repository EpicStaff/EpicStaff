"""What plugins_db holds under one plugin's database and role names, and whether it is this
installation's.

Provisioning adopts, and the removal drops, only what this installation created. The owner role
carries the installation marker as its comment, `epicstaff-plugin-installation:<installation
id>`. Roles or a database of these names without the marker are probably left from another
EpicStaff database; adopting them would show one organization's plugin data to another that got
the same ids, and dropping them would delete another installation's data.
"""

from dataclasses import dataclass

import psycopg
from src.shared.models.plugin_nodes import DesiredDatabase

INSTALLATION_MARKER_PREFIX = "epicstaff-plugin-installation:"
_OWNER_MARKER = (
    "SELECT d.description FROM pg_catalog.pg_shdescription d "
    "JOIN pg_catalog.pg_roles r ON r.oid = d.objoid "
    "WHERE d.classoid = 'pg_catalog.pg_authid'::pg_catalog.regclass AND r.rolname = %s"
)


def installation_marker(installation_id: str) -> str:
    return INSTALLATION_MARKER_PREFIX + installation_id


@dataclass(frozen=True)
class InstallationFootprint:
    """The three roles, the owner's marker and the named database's owner, as found."""

    roles: frozenset[str]
    owner_marker: str | None
    database_owner: str | None
    """Who owns the database of the desired name; None when there is none."""

    @property
    def absent(self) -> bool:
        """Nothing of these names is there."""
        return not self.roles and self.database_owner is None

    def is_ours(self, desired: DesiredDatabase) -> bool:
        """The owner carries this installation's marker and owns the database, if there is one."""
        return (
            desired.owner_role in self.roles
            and self.owner_marker == installation_marker(desired.installation_id)
            and self.database_owner in (None, desired.owner_role)
        )

    def found_objects(self, desired: DesiredDatabase) -> str:
        """What was found, for a conflict message: `role "x_owner", database "plugin_x"`."""
        objects = [
            f'role "{name}"'
            for name in (desired.owner_role, desired.app_role, desired.job_role)
            if name in self.roles
        ]
        if self.database_owner is not None:
            objects.append(f'database "{desired.database_name}"')
        return ", ".join(objects)


async def find_installation(
    admin: psycopg.AsyncConnection, desired: DesiredDatabase
) -> InstallationFootprint:
    """Read the footprint from `postgres`; nothing of the plugin's own database is opened."""
    names = [desired.owner_role, desired.app_role, desired.job_role]
    cursor = await admin.execute(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)", (names,)
    )
    roles = frozenset(row[0] for row in await cursor.fetchall())
    cursor = await admin.execute(_OWNER_MARKER, (desired.owner_role,))
    marker = await cursor.fetchone()
    cursor = await admin.execute(
        "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database WHERE datname = %s",
        (desired.database_name,),
    )
    database = await cursor.fetchone()
    return InstallationFootprint(
        roles=roles,
        owner_marker=marker[0] if marker else None,
        database_owner=database[0] if database else None,
    )
