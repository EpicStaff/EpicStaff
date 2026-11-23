import { HttpContext, HttpErrorResponse } from '@angular/common/http';

import { wasHandledByForbiddenInterceptor } from './forbidden-interceptor-handled.util';
import { SKIP_FORBIDDEN_RELOAD } from './skip-forbidden-reload.context';

function forbidden(body: unknown, status = 403): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body });
}

function envelope(code: string): object {
    return { type: 'client_error', errors: [{ code, detail: 'Not allowed.', attr: null, context: null }] };
}

describe('wasHandledByForbiddenInterceptor', () => {
    it.each([
        {
            case: 'a business-rule 403, envelope',
            error: forbidden(envelope('built_in_model_immutable')),
            handled: false,
        },
        { case: 'a permission 403, envelope', error: forbidden(envelope('permission_denied')), handled: true },
        { case: 'a 403 without a JSON body', error: forbidden('<html>Forbidden</html>'), handled: true },
        { case: 'a refusal that is no 403', error: forbidden(envelope('permission_denied'), 409), handled: false },
        { case: 'a failure that is not an HTTP error', error: new Error('boom'), handled: false },
    ])('is $handled for $case', ({ error, handled }) => {
        expect(wasHandledByForbiddenInterceptor(error)).toBe(handled);
    });

    it('is false for a request that asked to skip the forbidden reload', () => {
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true);

        expect(wasHandledByForbiddenInterceptor(forbidden(envelope('permission_denied')), context)).toBe(false);
    });
});
