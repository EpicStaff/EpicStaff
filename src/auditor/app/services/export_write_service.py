import asyncio
import csv
import json
import os
from pathlib import Path

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

    @classmethod
    def _write_csv_page(cls, writer: csv.DictWriter, page: list[BaseAuditEvent]) -> None:
        for event in page:
            row = event.model_dump(mode="json")
            writer.writerow({key: cls._to_csv_cell(value) for key, value in row.items()})

    @classmethod
    def _write_json_page(cls, f, page: list[BaseAuditEvent], *, is_first_page: bool) -> bool:
        for i, event in enumerate(page):
            if not is_first_page or i > 0:
                f.write(",")
            f.write(json.dumps(event.model_dump(mode="json")))
        return bool(page)

    @staticmethod
    async def run_export(
        job_id: str,
        body: type[BaseModel],
        claims: dict,
        pipeline: SearchPipeline,
        repository: AuditRepository,
        job_service: ExportJobService,
    ) -> None:
        try:
            org_id = claims["org_id"]
            retention_days = claims["retention_days"]

            filter_node = body.resolve_filter_node()

            os.makedirs(settings.AUDITOR_EXPORT_DATA_DIR, exist_ok=True)
            file_path = os.path.join(settings.AUDITOR_EXPORT_DATA_DIR, f"{job_id}.{body.format}")

            seen_ids: set[str] = set()
            row_count = 0
            truncated = False

            f = await asyncio.to_thread(open, file_path, "w", newline="")
            try:
                csv_writer = None
                wrote_any_json_row = False
                if body.format == "csv":
                    csv_writer = csv.DictWriter(
                        f, fieldnames=list(pipeline.event_model.model_fields)
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
                            ExportWriteService._write_csv_page, csv_writer, new_rows
                        )
                    else:
                        wrote_any_json_row = await asyncio.to_thread(
                            ExportWriteService._write_json_page,
                            f,
                            new_rows,
                            is_first_page=not wrote_any_json_row,
                        )

                    row_count += len(new_rows)
                    if truncated:
                        break

                if body.format == "json":
                    await asyncio.to_thread(f.write, "]")

            finally:
                await asyncio.to_thread(f.close)

            was_recorded = await job_service.mark_done(job_id, file_path, truncated)

            if not was_recorded:
                Path(file_path).unlink(missing_ok=True)

        except Exception:
            logger.exception("Export job {} failed", job_id)
            if "file_path" in locals():
                try:
                    await asyncio.to_thread(Path(file_path).unlink, missing_ok=True)
                except Exception:
                    logger.exception("Failed to clean up partial export file for job {}", job_id)
            await job_service.mark_failed(job_id)
