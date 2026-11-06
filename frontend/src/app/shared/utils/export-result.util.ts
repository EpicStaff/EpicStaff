import { HttpResponse } from '@angular/common/http';

import { ExcludedExportEntity, ExportResult } from '../models/export-result.model';

export const EXPORT_EXCLUDED_HEADER = 'X-Export-Excluded';

export function toExportResult(response: HttpResponse<Blob>): ExportResult {
    return {
        blob: response.body ?? new Blob(),
        excluded: parseExcludedHeader(response.headers.get(EXPORT_EXCLUDED_HEADER)),
    };
}

function parseExcludedHeader(header: string | null): ExcludedExportEntity[] {
    if (!header) {
        return [];
    }
    let parsed: unknown;
    try {
        parsed = JSON.parse(header);
    } catch {
        return [];
    }
    if (!Array.isArray(parsed)) {
        return [];
    }
    return parsed.every(isExcludedExportEntity) ? parsed : [];
}

function isExcludedExportEntity(value: unknown): value is ExcludedExportEntity {
    if (typeof value !== 'object' || value === null) {
        return false;
    }
    const { type, count, names } = value as Record<string, unknown>;
    return (
        typeof type === 'string' &&
        typeof count === 'number' &&
        Array.isArray(names) &&
        names.every((name) => typeof name === 'string')
    );
}
