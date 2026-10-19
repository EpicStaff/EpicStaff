import { HttpErrorResponse, HttpRequest } from '@angular/common/http';
import { ApiErrorItem } from '@shared/models';
import { throwError } from 'rxjs';

import { validationErrorsInterceptor } from '../../core/interceptors/validation-errors.interceptor';
import { extractFieldErrorMessages, extractHttpErrorMessage } from './http-error.util';

function badRequest(errors: Record<string, unknown>): HttpErrorResponse {
    return new HttpErrorResponse({ status: 400, error: { errors } });
}

describe('extractHttpErrorMessage for bulk-save node uuid errors', () => {
    it('reads a per-node uuid error', () => {
        const error = badRequest({
            python_node_list: [
                { index: 0, errors: { uuid: ['This uuid is already used by another node of this flow.'] } },
            ],
            task_node_list: [
                { index: 1, errors: { uuid: ['This uuid is used by more than one node in the request.'] } },
            ],
        });

        expect(extractHttpErrorMessage(error)).toBe(
            'uuid: This uuid is already used by another node of this flow.; ' +
                'uuid: This uuid is used by more than one node in the request.'
        );
    });

    it('reads a per-node error for a node that targets another flow', () => {
        const error = badRequest({ python_node_list: [{ index: 0, errors: { graph: ['Must be this flow.'] } }] });

        expect(extractHttpErrorMessage(error)).toBe('graph: Must be this flow.');
    });

    it('reads the top-level uuid conflict the backend reports when a save races another one', () => {
        const error = badRequest({ nodes: ['This uuid is already used by another node of this flow.'] });

        expect(extractHttpErrorMessage(error)).toBe('nodes: This uuid is already used by another node of this flow.');
    });
});

const FIELD = 'reasoning_effort';

/** The error as the app's components receive it: after validationErrorsInterceptor has seen it. */
function received(response: HttpErrorResponse): HttpErrorResponse {
    let intercepted: HttpErrorResponse | undefined;
    validationErrorsInterceptor(new HttpRequest('POST', '/api/llm-configs/', null), () =>
        throwError(() => response)
    ).subscribe({ error: (error: HttpErrorResponse) => (intercepted = error) });
    return intercepted!;
}

function rejected(errors: ApiErrorItem[], message = 'Validation failed.', status = 400): HttpErrorResponse {
    return received(
        new HttpErrorResponse({ status, error: { status_code: status, code: 'validation_error', message, errors } })
    );
}

describe('extractFieldErrorMessages', () => {
    it.each([
        {
            case: 'a single error for the field',
            errors: [{ field: FIELD, value: 'xhigh', reason: "Model 'm' does not support reasoning effort 'xhigh'." }],
            expected: ["Model 'm' does not support reasoning effort 'xhigh'."],
        },
        {
            case: 'the field among other fields',
            errors: [
                { field: 'custom_name', value: 'a', reason: 'Name taken.' },
                { field: FIELD, value: 'xhigh', reason: 'Not supported.' },
                { field: 'temperature', value: 3, reason: 'Too high.' },
            ],
            expected: ['Not supported.'],
        },
        {
            case: 'several errors for the field',
            errors: [
                { field: FIELD, value: 'xhigh', reason: 'First.' },
                { field: FIELD, value: 'xhigh', reason: 'Second.' },
            ],
            expected: ['First.', 'Second.'],
        },
        {
            case: 'a reason containing the separator the backend joins messages with',
            errors: [{ field: FIELD, value: 'xhigh', reason: "Model 'a; b' does not support 'xhigh'." }],
            expected: ["Model 'a; b' does not support 'xhigh'."],
        },
        {
            case: 'only other fields',
            errors: [{ field: 'custom_name', value: 'a', reason: 'Name taken.' }],
            expected: [],
        },
        {
            case: 'a field whose name only starts with the field name',
            errors: [{ field: 'reasoning_effort_level', value: 'xhigh', reason: 'Not supported.' }],
            expected: [],
        },
        {
            case: 'an empty reason for the field',
            errors: [
                { field: FIELD, value: 'xhigh', reason: '' },
                { field: FIELD, value: 'xhigh', reason: 'Not supported.' },
            ],
            expected: ['Not supported.'],
        },
        {
            case: 'an empty list',
            errors: [],
            expected: [],
        },
    ])('reads $case from the structured errors', ({ errors, expected }) => {
        expect(extractFieldErrorMessages(rejected(errors), FIELD)).toEqual(expected);
    });

    it.each([
        {
            case: 'an envelope whose message names the field but carries no errors list',
            response: new HttpErrorResponse({
                status: 400,
                error: { status_code: 400, code: 'invalid', message: 'custom_name: Taken.; reasoning_effort: Bad.' },
            }),
        },
        {
            case: 'an errors list on a status the interceptor does not treat as validation',
            response: new HttpErrorResponse({
                status: 500,
                error: { errors: [{ field: FIELD, value: 'xhigh', reason: 'Not supported.' }] },
            }),
        },
        { case: 'a string body', response: new HttpErrorResponse({ status: 400, error: 'reasoning_effort: Bad.' }) },
        { case: 'no body', response: new HttpErrorResponse({ status: 0 }) },
    ])('returns nothing for $case', ({ response }) => {
        expect(extractFieldErrorMessages(received(response), FIELD)).toEqual([]);
    });
});
