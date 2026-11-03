import { HttpErrorResponse } from '@angular/common/http';

/**
 * Whether the server refused the request itself (4xx): its message is about what was sent, e.g. a field it
 * rejected or a permission it needs, so a form shows it next to the fields. A network failure (0) or a server
 * error (5xx) is not.
 */
export function isClientError(error: HttpErrorResponse): boolean {
    return error.status >= 400 && error.status < 500;
}
