import csv
import io
import json
from abc import ABC, abstractmethod

from django.http import HttpResponse

from tables.import_export.archive import ExportArchiveWriter
from tables.import_export.enums import EntityType
from tables.import_export.export_exclusions import (
    EXPORT_EXCLUDED_HEADER,
    ExcludedEntity,
    build_excluded_header_value,
)
from tables.import_export.export_tabular_projections._csv_helpers import _neutralize_formula
from tables.import_export.export_tabular_projections.base import TabularProjection
from tables.import_export.registry import entity_registry
from tables.utils.helpers import generate_file_name


def apply_excluded_header(response: HttpResponse, excluded: list[ExcludedEntity]) -> None:
    header_value = build_excluded_header_value(excluded)
    if header_value is not None:
        response[EXPORT_EXCLUDED_HEADER] = header_value


class ExportFormatStrategy(ABC):
    @abstractmethod
    def render(
        self,
        data: dict,
        entity_type: str,
        prefix: str,
        base_name: str,
        excluded: list[ExcludedEntity] | None = None,
    ) -> HttpResponse: ...


class JsonExportFormatStrategy(ExportFormatStrategy):
    def render(
        self,
        data: dict,
        entity_type: str,
        prefix: str,
        base_name: str,
        excluded: list[ExcludedEntity] | None = None,
    ) -> HttpResponse:
        filename = generate_file_name(base_name, prefix=prefix)
        response = HttpResponse(json.dumps(data, indent=4), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        apply_excluded_header(response, excluded or [])
        return response


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


class CsvExportFormatStrategy(ExportFormatStrategy):
    def __init__(self, projection: TabularProjection):
        self.projection = projection

    def render(
        self,
        data: dict,
        entity_type: str,
        prefix: str,
        base_name: str,
        excluded: list[ExcludedEntity] | None = None,
    ) -> HttpResponse:
        rows = self.projection.expand_all(data.get(entity_type, []))

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=self.projection.FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: ("" if v is None else _neutralize_formula(v))
                    for k, v in self.projection.project(row).items()
                }
            )

        filename = generate_file_name(base_name, prefix=prefix).replace(".json", ".csv")
        response = HttpResponse(buf.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        apply_excluded_header(response, excluded or [])
        return response
