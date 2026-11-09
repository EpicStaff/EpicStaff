import csv
import json
import textwrap
from collections.abc import Iterable
from typing import TextIO

from tables.import_export.archive import ExportArchiveWriter
from tables.import_export.constants import IMPORT_VERSION, MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType
from tables.import_export.export_tabular_projections._csv_helpers import _neutralize_formula
from tables.import_export.export_tabular_projections.base import TabularProjection
from tables.import_export.registry import entity_registry


class ArchiveExportFormatStrategy:
    """Write an export as a zip archive: `export.json` plus the files it names.

    The archive can be far larger than a response should hold, so it is written
    to a temporary file; the export job stores and serves that file.
    """

    def render_to_file(self, result) -> str:
        """Write `result` (an ExportResult) into a temporary zip and return its path.

        The caller owns the file from then on and deletes it. Nothing is left
        behind when writing fails.
        """
        strategy = entity_registry.get_strategy(EntityType.SOURCE_COLLECTION)
        with ExportArchiveWriter() as writer:
            writer.write_envelope(result.data)
            # The files follow the serialized entries, so the archive holds exactly
            # what export.json names.
            for entry in result.data.get(EntityType.SOURCE_COLLECTION, []):
                strategy.write_archive_members(entry, writer)
        return writer.path


class CsvExportFormatStrategy:
    """Write the exported entries of one type as CSV, one row per projected row."""

    def __init__(self, projection: TabularProjection):
        self.projection = projection

    def write(self, data: dict, entity_type: str, stream: TextIO) -> None:
        """Write the header and every row of `data[entity_type]` into `stream`.

        The projection expands all entries before the first row is written, so the
        whole export is in memory; a large export streams its rows into `write_rows`.
        """
        self.write_rows(self.projection.expand_all(data.get(entity_type, [])), stream)

    def write_rows(self, rows: Iterable[dict], stream: TextIO) -> None:
        """Write the header, then each expanded row as `rows` yields it.

        Values a spreadsheet would run as a formula are neutralized.
        """
        writer = csv.DictWriter(stream, fieldnames=self.projection.FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: ("" if value is None else _neutralize_formula(value))
                    for key, value in self.projection.project(row).items()
                }
            )


_JSON_INDENT = " " * 4


def write_json_envelope(entity_type: EntityType, entries: Iterable[dict], stream: TextIO) -> None:
    """Write the envelope `ExportService` builds for `entries`, one entry at a time.

    The text is what `json.dump(envelope, stream, indent=4)` writes for
    `{entity_type: entries, "main_entity": entity_type, "version": IMPORT_VERSION}`,
    but only one entry is held in memory at once.
    """
    stream.write("{\n" + _JSON_INDENT + json.dumps(entity_type) + ": [")
    separator = "\n"
    for entry in entries:
        stream.write(separator + textwrap.indent(json.dumps(entry, indent=4), _JSON_INDENT * 2))
        separator = ",\n"
    if separator != "\n":
        stream.write("\n" + _JSON_INDENT)
    stream.write("]")
    stream.writelines(
        ",\n" + _JSON_INDENT + json.dumps(key) + ": " + json.dumps(value)
        for key, value in ((MAIN_ENTITY_KEY, entity_type), ("version", IMPORT_VERSION))
    )
    stream.write("\n}")
