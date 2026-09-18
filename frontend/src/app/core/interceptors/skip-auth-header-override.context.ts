import { HttpContextToken } from '@angular/common/http';

/**
 * Marks a request as already carrying its own Authorization header that must not be
 * overwritten - e.g. a call to the standalone auditor service, which needs the short-lived
 * audit-scoped JWT from AuditTokenService, not the regular user access token authInterceptor
 * attaches by default.
 */
export const SKIP_AUTH_HEADER_OVERRIDE = new HttpContextToken<boolean>(() => false);
