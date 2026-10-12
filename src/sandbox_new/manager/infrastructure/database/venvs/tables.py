from piccolo.columns import JSONB, Serial, Text, Timestamp, Varchar
from piccolo.columns.defaults.timestamp import TimestampNow
from piccolo.table import Table

from manager.domain.enums import VenvStatus


class VenvTable(Table, tablename="venv"):
    id: Serial
    name = Varchar()
    libs = JSONB(default=list)
    hash = Varchar(null=True, default=None)
    status = Varchar(length=20, choices=VenvStatus, default=VenvStatus.DECLARED)
    error = Text(null=True, default=None)
    created_at = Timestamp(default=TimestampNow())
    updated_at = Timestamp(default=TimestampNow())
