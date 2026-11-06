from piccolo.columns import JSONB, Serial, Text, Timestamptz, Varchar
from piccolo.columns.defaults.timestamptz import TimestamptzNow
from piccolo.table import Table

from manager.domain.enums import VenvBuildErrorKind, VenvStatus


class VenvTable(Table, tablename="venv"):
    id: Serial
    name = Varchar()
    libs = JSONB(default=list)
    hash = Varchar(null=True, default=None)
    status = Varchar(length=20, choices=VenvStatus, default=VenvStatus.DECLARED)
    error = Text(null=True, default=None)
    error_kind = Varchar(length=40, null=True, default=None, choices=VenvBuildErrorKind)
    created_at = Timestamptz(default=TimestamptzNow())
    updated_at = Timestamptz(default=TimestamptzNow())
