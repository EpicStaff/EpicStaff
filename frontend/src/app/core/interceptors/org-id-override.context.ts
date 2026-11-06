import { HttpContextToken } from '@angular/common/http';

/**
 * Per-request override for the `X-Organization-Id` header normally injected
 * by `activeOrgInterceptor`.
 *
 * | Token value | Header behaviour                                                  |
 * |-------------|-------------------------------------------------------------------|
 * | `undefined` | Not set → interceptor falls back to active-org logic              |
 * | `null`      | Explicitly omit the header (superadmin cross-org view)            |
 * | `number`    | Use this org id instead of the active org                         |
 *
 * A `number` is honoured for every user: it pins a request to an organization the user worked in, such as
 * the one a background job was started in, and the backend checks the user's membership of it as for any
 * header. `null` is honoured only for a superadmin; for anyone else the interceptor applies its default
 * active-org logic.
 */
export const ORG_ID_OVERRIDE = new HttpContextToken<number | null | undefined>(() => undefined);
