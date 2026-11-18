from enum import Enum

from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import (
    Boolean,
    ForeignKey,
    OnDelete,
    OnUpdate,
    Serial,
    Text,
    Timestamptz,
    Varchar,
)
from piccolo.columns.defaults.timestamptz import TimestamptzNow
from piccolo.columns.indexes import IndexMethod
from piccolo.table import Table

ID = "2026-11-02T12:00:00:000000"
VERSION = "1.36.0"
DESCRIPTION = "Add the custom_library and wheel tables"


class CustomLibraryTable(Table, tablename="custom_library", schema=None):
    id = Serial(
        null=False,
        primary_key=True,
        unique=False,
        index=False,
        index_method=IndexMethod.btree,
        choices=None,
        db_column_name="id",
        secret=False,
    )


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    manager.add_table(
        class_name="CustomLibraryTable",
        tablename="custom_library",
        schema=None,
        columns=None,
    )

    manager.add_table(class_name="WheelTable", tablename="wheel", schema=None, columns=None)

    manager.add_column(
        table_class_name="CustomLibraryTable",
        tablename="custom_library",
        column_name="name",
        db_column_name="name",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 255,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="CustomLibraryTable",
        tablename="custom_library",
        column_name="is_deleted",
        db_column_name="is_deleted",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": False,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="CustomLibraryTable",
        tablename="custom_library",
        column_name="created_at",
        db_column_name="created_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "default": TimestamptzNow(),
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="CustomLibraryTable",
        tablename="custom_library",
        column_name="updated_at",
        db_column_name="updated_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "default": TimestamptzNow(),
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="library",
        db_column_name="library",
        column_class_name="ForeignKey",
        column_class=ForeignKey,
        params={
            "references": CustomLibraryTable,
            "on_delete": OnDelete.cascade,
            "on_update": OnUpdate.cascade,
            "target_column": None,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="source_filename",
        db_column_name="source_filename",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 255,
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="wheel_filename",
        db_column_name="wheel_filename",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 255,
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="upload_sha256",
        db_column_name="upload_sha256",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 64,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="version",
        db_column_name="version",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 255,
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="status",
        db_column_name="status",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 20,
            "default": "declared",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": Enum(
                "WheelStatus",
                {
                    "DECLARED": "declared",
                    "PROCESSING": "processing",
                    "COMPLETED": "completed",
                    "FAILED": "failed",
                },
            ),
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="error",
        db_column_name="error",
        column_class_name="Text",
        column_class=Text,
        params={
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="is_deleted",
        db_column_name="is_deleted",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": False,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="WheelTable",
        tablename="wheel",
        column_name="created_at",
        db_column_name="created_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "default": TimestamptzNow(),
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    return manager
