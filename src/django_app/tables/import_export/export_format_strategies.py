import csv
import io
import json
from abc import ABC, abstractmethod

from django.http import HttpResponse

from tables.import_export.export_exclusions import (
    EXPORT_EXCLUDED_HEADER,
    ExcludedEntity,
    build_excluded_header_value,
)
from tables.import_export.export_tabular_projections._csv_helpers import _neutralize_formula
from tables.import_export.export_tabular_projections.base import TabularProjection
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
