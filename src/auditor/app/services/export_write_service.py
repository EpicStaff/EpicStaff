import asyncio
import csv
import json
import os
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core import settings
from app.repositories.base import AuditRepository
from app.services.export_job_service import ExportJobService
from app.services.search_pipeline import SearchPipeline
from loguru import logger
from pydantic import BaseModel
from src.shared.models.audit.base import BaseAuditEvent

# Leading characters spreadsheet applications interpret as the start of a
# formula (tab and carriage return included, per OWASP CSV injection guidance).
_CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


class ExportWriteService:
    @staticmethod
    def _to_csv_cell(value):
        """Serializes nested values to JSON and neutralizes spreadsheet
        formulas: exported cells carry LLM and user content, and a cell that
        starts with a formula trigger would execute when opened in a
        spreadsheet application."""
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        if isinstance(value, str) and value.startswith(_CSV_FORMULA_TRIGGERS):
            return f"'{value}"
        return value

    @staticmethod
    def _public_row(event: BaseAuditEvent, zone: ZoneInfo | None) -> dict[str, Any]:
        """Return the event's public fields, with every datetime field written in
        `zone` as ISO 8601 with that zone's offset. Without a zone the row is the
        event's own `public_dump()`, unchanged."""
        row = event.public_dump()
        if zone is None:
            return row
        for name in row:
            value = getattr(event, name)
            if isinstance(value, datetime):
                # A naive time is UTC: producers record UTC, and astimezone() would
                # otherwise read it in the auditor host's own zone.
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                row[name] = value.astimezone(zone).isoformat()
        return row

    @classmethod
    def _write_csv_page(
        cls, writer: csv.DictWriter, page: list[BaseAuditEvent], zone: ZoneInfo | None
    ) -> None:
        for event in page:
            row = cls._public_row(event, zone)
            writer.writerow({key: cls._to_csv_cell(value) for key, value in row.items()})

    @classmethod
    def _write_json_page(
        cls, f, page: list[BaseAuditEvent], zone: ZoneInfo | None, *, is_first_page: bool
    ) -> bool:
        """Pretty-prints each event (2-space indent, one level inside the
        array) and keeps non-ASCII text readable instead of \\u-escaped."""
        for i, event in enumerate(page):
            f.write("\n" if is_first_page and i == 0 else ",\n")
            event_json = json.dumps(cls._public_row(event, zone), indent=2, ensure_ascii=False)
            f.write(textwrap.indent(event_json, "  "))
        return bool(page)

    @staticmethod
    async def run_export(
        job_id: str,
        body: BaseModel,
        claims: dict,
        pipeline: SearchPipeline,
        repository: AuditRepository,
        job_service: ExportJobService,
    ) -> None:
        file_path: str | None = None
        try:
            org_id = claims["org_id"]
            retention_days = claims["retention_days"]

            filter_node = body.resolve_filter_node()
            zone = ZoneInfo(body.time_zone) if body.time_zone else None

            os.makedirs(settings.AUDITOR_EXPORT_DATA_DIR, exist_ok=True)
            file_path = os.path.join(settings.AUDITOR_EXPORT_DATA_DIR, f"{job_id}.{body.format}")

            seen_ids: set[str] = set()
            row_count = 0
            truncated = False

            f = await asyncio.to_thread(open, file_path, "w", newline="", encoding="utf-8")
            try:
                csv_writer = None
                wrote_any_json_row = False
                if body.format == "csv":
                    csv_writer = csv.DictWriter(
                        f, fieldnames=pipeline.event_model.public_field_names()
                    )
                    await asyncio.to_thread(csv_writer.writeheader)
                else:
                    await asyncio.to_thread(f.write, "[")

                async for page in pipeline.scan(
                    repository,
                    filter_node,
                    getattr(body, "match_scope", None),
                    org_id=org_id,
                    retention_days=retention_days,
                ):
                    new_rows = [e for e in page if e.id not in seen_ids]
                    if not new_rows:
                        continue
                    seen_ids.update(e.id for e in new_rows)

                    if row_count + len(new_rows) > settings.AUDITOR_EXPORT_MAX_ROWS:
                        allowed = settings.AUDITOR_EXPORT_MAX_ROWS - row_count
                        new_rows = new_rows[:allowed]
                        truncated = True

                    if body.format == "csv":
                        await asyncio.to_thread(
                            ExportWriteService._write_csv_page, csv_writer, new_rows, zone
                        )
                    else:
                        wrote_any_json_row = await asyncio.to_thread(
                            ExportWriteService._write_json_page,
                            f,
                            new_rows,
                            zone,
                            is_first_page=not wrote_any_json_row,
                        )

                    row_count += len(new_rows)
                    if truncated:
                        break

                if body.format == "json":
                    await asyncio.to_thread(f.write, "\n]\n" if wrote_any_json_row else "]")

            finally:
                await asyncio.to_thread(f.close)

            was_recorded = await job_service.mark_done(job_id, file_path, truncated)

            if not was_recorded:
                Path(file_path).unlink(missing_ok=True)

        except Exception:
            logger.exception("Export job {} failed", job_id)
            if file_path is not None:
                try:
                    await asyncio.to_thread(Path(file_path).unlink, missing_ok=True)
                except Exception:
                    logger.exception("Failed to clean up partial export file for job {}", job_id)
            await job_service.mark_failed(job_id)
