import { ExportFormat } from '../../../core/models/transfer-job.model';
import { ExportJobRequests, SessionExportFilters } from '../../../core/services/transfer-jobs.service';

/** The filters of a sessions list that an export of every matching session can apply. */
export interface SessionListExportFilters {
    graphId?: number | null;
    /** Session statuses; none or empty for every status. */
    statuses?: string[] | null;
    errorCauseOnly?: boolean;
    idSearch?: string | null;
}

/**
 * The export of the selected sessions, or, with none selected, of every session that matches the list's filters.
 * A filter left at its default is left out, so it does not narrow the export.
 */
export function sessionExportRequest(
    selectedIds: ReadonlySet<number>,
    filters: SessionListExportFilters,
    format: ExportFormat
): ExportJobRequests['sessions'] {
    if (selectedIds.size > 0) {
        return { ids: [...selectedIds], export_format: format };
    }
    const body: SessionExportFilters = {};
    if (filters.graphId != null) body.graph_id = filters.graphId;
    if (filters.statuses && filters.statuses.length > 0) body.status = filters.statuses;
    if (filters.errorCauseOnly) body.is_error_cause = true;
    if (filters.idSearch) body.id_search = filters.idSearch;
    return { ...body, export_format: format };
}
