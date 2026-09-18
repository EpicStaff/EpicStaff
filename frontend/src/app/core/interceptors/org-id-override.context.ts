import { HttpContextToken } from '@angular/common/http';

/**
 * Per-request override for the `X-Organization-Id` header normally injected
 * by `activeOrgInterceptor`.
 *
 * | Token value | Header behaviour                                      |
 * |-------------|-------------------------------------------------------|
 * | `undefined` | Not set → interceptor falls back to active-org logic  |
 * | `null`      | Explicitly omit the header (superadmin cross-org view)|
 * | `number`    | Use this org id instead of the active org             |
 *
 * Only honoured when the requesting user is a superadmin; for regular users
 * the interceptor always applies its default active-org logic regardless.
 */
export const ORG_ID_OVERRIDE = new HttpContextToken<number | null | undefined>(() => undefined);
