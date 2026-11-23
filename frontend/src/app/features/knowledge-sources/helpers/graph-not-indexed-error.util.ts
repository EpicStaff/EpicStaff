import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { extractErrorCode } from '@shared/utils';

import { GRAPH_NOT_INDEXED_ERROR_CODE } from '../constants/constants';

/**
 * True only for the backend's "graph not indexed" answer. Other conflicts also arrive as 409 (with a different
 * `code`, e.g. an upstream resource conflict) and must be shown as plain load errors, not as "run indexing first".
 */
export function isGraphNotIndexedError(error: HttpErrorResponse): boolean {
    return error.status === HttpStatusCode.Conflict && extractErrorCode(error) === GRAPH_NOT_INDEXED_ERROR_CODE;
}
