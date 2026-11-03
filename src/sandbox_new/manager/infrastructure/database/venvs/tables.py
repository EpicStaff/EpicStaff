from piccolo.columns import (
    JSONB,
    Boolean,
    ForeignKey,
    OnDelete,
    Serial,
    Text,
    Timestamptz,
    Varchar,
)
from piccolo.columns.defaults.timestamptz import TimestamptzNow
from piccolo.table import Table

from manager.domain.enums import VenvStatus, WheelStatus


class VenvTable(Table, tablename="venv"):
    id: Serial
    name = Varchar()
    libs = JSONB(default=list)
    hash = Varchar(null=True, default=None)
    status = Varchar(length=20, choices=VenvStatus, default=VenvStatus.DECLARED)
    error = Text(null=True, default=None)
    created_at = Timestamptz(default=TimestamptzNow())
    updated_at = Timestamptz(default=TimestamptzNow())


class CustomLibraryTable(Table, tablename="custom_library"):
    id: Serial
    name = Varchar()
    is_deleted = Boolean(default=False)
    created_at = Timestamptz(default=TimestamptzNow())
    updated_at = Timestamptz(default=TimestamptzNow())


class WheelTable(Table, tablename="wheel"):
    id: Serial
    library = ForeignKey(references=CustomLibraryTable, on_delete=OnDelete.cascade, null=False)
    source_filename = Varchar(null=True, default=None)
    wheel_filename = Varchar(null=True, default=None)
    upload_sha256 = Varchar(length=64)
    version = Varchar(null=True, default=None)
    status = Varchar(length=20, choices=WheelStatus, default=WheelStatus.DECLARED)
    error = Text(null=True, default=None)
    is_deleted = Boolean(default=False)
    created_at = Timestamptz(default=TimestamptzNow())
