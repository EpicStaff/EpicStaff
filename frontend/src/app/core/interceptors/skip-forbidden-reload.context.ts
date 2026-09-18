import { HttpContextToken } from '@angular/common/http';

/**
 * Marks a request as expected to sometimes 403 for roles that simply don't have access to that
 * resource (e.g. a member/viewer's secret picker fetching /secrets/) — a permanent, per-role
 * restriction, not a sign of stale cached permissions. Without this, forbiddenInterceptor treats
 * every 403 as stale and re-navigates to the current URL, which just remounts the same
 * component, re-fires the same request, and 403s again — an infinite reload loop for pages that
 * always issue this request (e.g. a saved node with a secrets field).
 */
export const SKIP_FORBIDDEN_RELOAD = new HttpContextToken<boolean>(() => false);
