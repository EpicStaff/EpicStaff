from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from enum import Enum
from piccolo.columns.column_types import Varchar
from piccolo.columns.indexes import IndexMethod

ID = "2026-11-06T14:54:46:350778"
VERSION = "1.36.0"
DESCRIPTION = "Store why a venv build failed in venv.error_kind; rows failed earlier stay NULL"


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="venvs", description=DESCRIPTION
    )

    # Backwards, MigrationManager drops a column it added, so no raw step is needed.
    manager.add_column(
        table_class_name="VenvTable",
        tablename="venv",
        column_name="error_kind",
        db_column_name="error_kind",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 40,
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": Enum(
                "VenvBuildErrorKind",
                {
                    "PACKAGE_NOT_FOUND": "package_not_found",
                    "PACKAGE_VERSION_NOT_FOUND": "package_version_not_found",
                    "PACKAGE_DEPENDENCY_CONFLICT": "package_dependency_conflict",
                    "PACKAGE_INSTALL_FAILED": "package_install_failed",
                },
            ),
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    return manager
