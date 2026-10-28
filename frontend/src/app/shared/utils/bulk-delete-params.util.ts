import { HttpParams } from '@angular/common/http';
import { BulkDeleteOptions } from '@shared/models';

/**
 * Builds the query params for a bulk-delete request.
 * `dry_run` must travel only in the query string — the backend ignores `dry_run`
 * in the request body and deletes for real.
 */
export function bulkDeleteParams(options: BulkDeleteOptions = {}): HttpParams {
    return options.dryRun ? new HttpParams().set('dry_run', 'true') : new HttpParams();
}
