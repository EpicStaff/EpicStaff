import { HttpErrorResponse } from '@angular/common/http';

import {
    extractErrorCode,
    extractErrorContext,
    extractFieldErrorMessages,
    extractFieldErrors,
    extractHttpErrorMessage,
    extractServerMessage,
    httpFailureReason,
    sessionErrorItem,
    toApiErrors,
} from './http-error.util';

function envelope(status: number, errors: unknown[]): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: { type: 'client_error', errors } });
}

function errorResponse(status: number, body: unknown): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body, url: 'http://api.test/venvs/' });
}

const FIELD = 'reasoning_effort';

function rejected(status: number, fieldErrors: { attr: string | null; detail: string }[]): HttpErrorResponse {
    return envelope(
        status,
        fieldErrors.map(({ attr, detail }) => ({ code: 'invalid', detail, attr, context: null }))
    );
}

describe('extractFieldErrorMessages', () => {
    it.each<{ case: string; status?: number; errors: { attr: string | null; detail: string }[]; expected: string[] }>([
        {
            case: 'a single error for the field',
            errors: [{ attr: FIELD, detail: "Model 'm' does not support reasoning effort 'xhigh'." }],
            expected: ["Model 'm' does not support reasoning effort 'xhigh'."],
        },
        {
            case: 'the field among other fields and a whole-form error',
            errors: [
                { attr: 'custom_name', detail: 'Name taken.' },
                { attr: FIELD, detail: 'Not supported.' },
                { attr: 'temperature', detail: 'Too high.' },
                { attr: null, detail: 'The whole form is wrong.' },
            ],
            expected: ['Not supported.'],
        },
        {
            case: 'the field of a 422',
            status: 422,
            errors: [{ attr: FIELD, detail: 'Not supported.' }],
            expected: ['Not supported.'],
        },
        {
            case: 'the field of a status that is not a validation error, as nothing',
            status: 409,
            errors: [{ attr: FIELD, detail: 'Not supported.' }],
            expected: [],
        },
        {
            case: 'several errors for the field',
            errors: [
                { attr: FIELD, detail: 'First.' },
                { attr: FIELD, detail: 'Second.' },
            ],
            expected: ['First.', 'Second.'],
        },
        {
            case: 'a detail containing the separator messages are joined with',
            errors: [{ attr: FIELD, detail: "Model 'a; b' does not support 'xhigh'." }],
            expected: ["Model 'a; b' does not support 'xhigh'."],
        },
        {
            case: 'only other fields',
            errors: [{ attr: 'custom_name', detail: 'Name taken.' }],
            expected: [],
        },
        {
            case: 'a field whose name only starts with the field name',
            errors: [{ attr: 'reasoning_effort_level', detail: 'Not supported.' }],
            expected: [],
        },
        {
            case: 'an empty detail for the field',
            errors: [
                { attr: FIELD, detail: '' },
                { attr: FIELD, detail: 'Not supported.' },
            ],
            expected: ['Not supported.'],
        },
        {
            case: 'an empty list',
            errors: [],
            expected: [],
        },
    ])('reads $case from the envelope', ({ status = 400, errors, expected }) => {
        expect(extractFieldErrorMessages(rejected(status, errors), FIELD)).toEqual(expected);
    });

    it.each([
        {
            case: 'a body that is not the envelope, even when it names the field',
            response: new HttpErrorResponse({
                status: 400,
                error: { errors: [{ field: FIELD, reason: 'Not supported.' }], reasoning_effort: ['Bad.'] },
            }),
        },
        { case: 'a string body', response: new HttpErrorResponse({ status: 400, error: 'reasoning_effort: Bad.' }) },
        { case: 'no body', response: new HttpErrorResponse({ status: 0 }) },
    ])('returns nothing for $case', ({ response }) => {
        expect(extractFieldErrorMessages(response, FIELD)).toEqual([]);
    });
});

describe('extractHttpErrorMessage', () => {
    it.each([
        [500, '<!DOCTYPE html>\n<html><body>ProgrammingError at /venvs/</body></html>', 'Server error (500)'],
        [502, '  <html><body>Bad Gateway</body></html>', 'Server error (502)'],
        [404, '<!doctype html><title>Not Found</title>', 'Request failed (404)'],
    ])('never shows an HTML page as the message (status %i)', (status, body, expected) => {
        expect(extractHttpErrorMessage(errorResponse(status, body))).toBe(expected);
    });

    it('uses the caller fallback instead of an HTML page when one is given', () => {
        expect(extractHttpErrorMessage(errorResponse(500, '<!DOCTYPE html><html></html>'), 'Could not save')).toBe(
            'Could not save'
        );
    });

    it('still shows a plain-text body', () => {
        expect(extractHttpErrorMessage(errorResponse(400, 'Name is taken'))).toBe('Name is taken');
    });

    it('shows the details of an errors envelope, deduplicated', () => {
        const body = {
            type: 'server_error',
            errors: [
                { code: 'unknown', detail: 'invalid input for query argument $6' },
                { code: 'unknown', detail: 'invalid input for query argument $6' },
                { code: 'invalid', detail: 'Version does not satisfy specification' },
            ],
        };

        expect(extractHttpErrorMessage(errorResponse(500, body))).toBe(
            'invalid input for query argument $6; Version does not satisfy specification'
        );
    });

    it.each([
        {
            case: 'the details of an envelope, each after its field',
            body: {
                type: 'client_error',
                errors: [{ code: 'blank', detail: 'This field may not be blank.', attr: 'name', context: null }],
            },
            expected: 'name: This field may not be blank.',
        },
        {
            case: 'the detail of an envelope item naming no field, alone',
            body: {
                type: 'client_error',
                errors: [{ code: 'invalid', detail: 'Names must be unique.', attr: 'non_field_errors' }],
            },
            expected: 'Names must be unique.',
        },
    ])('shows $case', ({ body, expected }) => {
        expect(extractHttpErrorMessage(errorResponse(400, body))).toBe(expected);
    });
});

describe('extractHttpErrorMessage for a refused storage grant', () => {
    it("gives the server's message so a failed save can show it", () => {
        const message =
            "This code runs with Files: Write, Files: Delete, which you don't have. Contact an admin to change it.";
        const error = envelope(403, [
            {
                code: 'storage_grant_denied',
                detail: message,
                attr: null,
                context: { missing_grants: ['write', 'delete'] },
            },
        ]);

        expect(extractHttpErrorMessage(error)).toBe(message);
    });
});

describe('httpFailureReason', () => {
    it.each([
        ['an unreachable server', 0, new ProgressEvent('error'), "The server couldn't be reached."],
        [
            'the reason a refusal gave',
            400,
            { type: 'client_error', errors: [{ code: 'invalid', detail: 'No node connected to start node' }] },
            'No node connected to start node',
        ],
        [
            'the reason a server error gave',
            500,
            { type: 'server_error', errors: [{ code: 'locked', detail: 'The flow is locked.' }] },
            'The flow is locked.',
        ],
        ['a refusal without a body', 400, null, 'The server rejected the request.'],
        ['a server error without a body', 500, null, 'Something went wrong on the server.'],
        ['a proxy error page', 502, '<html><body>Bad Gateway</body></html>', 'Something went wrong on the server.'],
        ['an HTML refusal page', 404, '<!doctype html><title>Not Found</title>', 'The server rejected the request.'],
        [
            "a proxy's page for a too-large upload",
            413,
            '<html><head><title>413 Request Entity Too Large</title></head></html>',
            'The server rejected the request.',
        ],
        ['an empty body', 503, '', 'Something went wrong on the server.'],
        [
            'a JSON body that is not the envelope',
            502,
            { message: 'upstream down' },
            'Something went wrong on the server.',
        ],
        [
            'a success page that could not be parsed',
            200,
            { error: new SyntaxError('x'), text: '<!doctype html>' },
            "The server's response couldn't be read.",
        ],
    ])('states %s', (_case, status, body, expected) => {
        expect(httpFailureReason(errorResponse(status, body))).toBe(expected);
    });

    it('does not blame the server for a failure thrown before any request was sent', () => {
        const thrownInTheApp = new TypeError("Cannot read properties of undefined (reading 'variables')");

        expect(httpFailureReason(thrownInTheApp)).toBe('Something went wrong.');
    });
});

describe('toApiErrors', () => {
    it.each([
        {
            case: 'the envelope, as it is',
            body: {
                type: 'client_error',
                errors: [
                    { code: 'max_length', detail: 'Too long.', attr: 'name', context: { max: 255 } },
                    { code: 'locked', detail: 'The flow is locked.', attr: null, context: null },
                ],
            },
            expected: [
                { code: 'max_length', detail: 'Too long.', attr: 'name', context: { max: 255 } },
                { code: 'locked', detail: 'The flow is locked.', attr: null, context: null },
            ],
        },
        {
            case: 'an envelope item that leaves out attr and context',
            body: { type: 'server_error', errors: [{ code: 'unknown', detail: 'Index failed.' }] },
            expected: [{ code: 'unknown', detail: 'Index failed.', attr: null, context: null }],
        },
        {
            case: 'an empty envelope',
            body: { type: 'client_error', errors: [] },
            expected: [],
        },
        {
            case: 'envelope items naming a whole-form key, as errors of no single field',
            body: {
                type: 'validation_error',
                errors: [
                    { code: 'invalid', detail: 'Names must be unique.', attr: 'non_field_errors' },
                    { code: 'invalid', detail: 'Sign-up is closed.', attr: '__all__' },
                ],
            },
            expected: [
                { code: 'invalid', detail: 'Names must be unique.', attr: null, context: null },
                { code: 'invalid', detail: 'Sign-up is closed.', attr: null, context: null },
            ],
        },
        {
            case: 'an envelope item whose path ends in a whole-form key, as an error of the item before it',
            body: {
                type: 'validation_error',
                errors: [{ code: 'invalid', detail: 'Bad node.', attr: 'task_node_list.3.non_field_errors' }],
            },
            expected: [{ code: 'invalid', detail: 'Bad node.', attr: 'task_node_list.3', context: null }],
        },
        {
            case: 'an envelope item without a detail, by skipping it',
            body: {
                type: 'client_error',
                errors: [{ code: 'invalid', attr: 'name' }, 'Required.', { code: 'blank', detail: 'Blank.' }],
            },
            expected: [{ code: 'blank', detail: 'Blank.', attr: null, context: null }],
        },
        {
            case: 'an envelope whose errors are no list, as nothing',
            body: { type: 'client_error', errors: { name: ['Required.'] } },
            expected: [],
        },
        {
            case: 'a body with the keys of an error but no envelope, as nothing',
            body: { status_code: 400, code: 'invalid', message: 'Validation failed', detail: 'Not found.' },
            expected: [],
        },
        { case: 'a bare validation dict, as nothing', body: { name: ['This field is required.'] }, expected: [] },
        { case: 'a plain-text body, which is not JSON', body: 'Name is taken', expected: [] },
        { case: 'an HTML page', body: '<!DOCTYPE html><html></html>', expected: [] },
        { case: 'an empty string', body: '', expected: [] },
        { case: 'no body', body: null, expected: [] },
    ])('reads $case', ({ body, expected }) => {
        expect(toApiErrors(body)).toEqual(expected);
    });
});

describe('extractErrorCode and extractErrorContext', () => {
    it.each([
        {
            case: 'an envelope',
            body: {
                type: 'client_error',
                errors: [
                    { code: 'run_limit_reached', detail: 'Too many runs.', attr: null, context: { limit: 5 } },
                    { code: 'other', detail: 'Other.', attr: null, context: null },
                ],
            },
            code: 'run_limit_reached',
            context: { limit: 5 },
        },
        {
            case: 'an envelope whose error names no code',
            body: { type: 'server_error', errors: [{ code: 'unknown', detail: 'Index failed.' }] },
            code: null,
            context: null,
        },
        {
            case: 'a body that is not the envelope',
            body: { code: 'message_too_long', message: 'Too long.', max: 4000 },
            code: null,
            context: null,
        },
        { case: 'a body without an error', body: null, code: null, context: null },
    ])('read the first error of $case', ({ body, code, context }) => {
        const error = errorResponse(409, body);

        expect(extractErrorCode(error)).toBe(code);
        expect(extractErrorContext(error)).toEqual(context);
    });

    it('read nothing from a failure that is not an HTTP error', () => {
        const thrownInTheApp = new TypeError('x is undefined');

        expect(extractErrorCode(thrownInTheApp)).toBeNull();
        expect(extractErrorContext(thrownInTheApp)).toBeNull();
    });
});

describe('extractServerMessage', () => {
    it.each([
        {
            case: 'the details of an envelope',
            body: {
                type: 'client_error',
                errors: [
                    { code: 'invalid', detail: 'Too short.', attr: 'password' },
                    { code: 'invalid', detail: 'Too common.', attr: null },
                ],
            },
            expected: 'password: Too short.; Too common.',
        },
        {
            case: 'a body that is not the envelope',
            body: { status_code: 409, code: 'conflict', message: 'Already set up.' },
            expected: null,
        },
        { case: 'a plain-text body', body: 'Bad gateway', expected: null },
        { case: 'an HTML page', body: '<html><body>Bad Gateway</body></html>', expected: null },
        { case: 'no body', body: null, expected: null },
    ])('reads $case', ({ body, expected }) => {
        expect(extractServerMessage(errorResponse(409, body))).toBe(expected);
    });

    it('reads nothing from a failure that is not an HTTP error', () => {
        expect(extractServerMessage(new Error('boom'))).toBeNull();
    });
});

describe('extractFieldErrors', () => {
    const envelopeFieldErrors = [
        { code: 'invalid', detail: 'Enter a valid email.', attr: 'email', context: null },
        { code: 'invalid', detail: 'Sign-up is closed.', attr: null, context: null },
    ];

    it.each([
        {
            case: 'the field errors of an envelope',
            status: 422,
            body: { type: 'client_error', errors: envelopeFieldErrors },
            expected: envelopeFieldErrors,
        },
        {
            case: 'nothing for an envelope naming no field',
            status: 400,
            body: {
                type: 'client_error',
                errors: [{ code: 'invalid_current_password', detail: 'Current password is incorrect.', attr: null }],
            },
            expected: [],
        },
        {
            case: 'nothing for an envelope naming only a whole-form key',
            status: 400,
            body: {
                type: 'validation_error',
                errors: [{ code: 'invalid', detail: 'Names must be unique.', attr: 'non_field_errors' }],
            },
            expected: [],
        },
        {
            case: 'nothing for field errors on a status that is no validation failure',
            status: 409,
            body: { type: 'client_error', errors: envelopeFieldErrors },
            expected: [],
        },
        {
            case: 'nothing for a body that is not the envelope',
            status: 400,
            body: { email: ['Enter a valid email.'] },
            expected: [],
        },
    ])('returns $case', ({ status, body, expected }) => {
        expect(extractFieldErrors(errorResponse(status, body))).toEqual(expected);
    });
});

describe('sessionErrorItem', () => {
    it.each([
        {
            case: 'the error item of a session error',
            messageData: {
                error: { code: 'node_failed', detail: 'The node failed.', attr: 'node.code', context: { line: 3 } },
            },
            expected: { code: 'node_failed', detail: 'The node failed.', attr: 'node.code', context: { line: 3 } },
        },
        {
            case: 'an error item that leaves out attr and context',
            messageData: { error: { code: 'node_failed', detail: 'The node failed.' } },
            expected: { code: 'node_failed', detail: 'The node failed.', attr: null, context: null },
        },
        { case: 'nothing from an error that is no item', messageData: { error: 'Division by zero' }, expected: null },
        { case: 'nothing from a message without an error', messageData: {}, expected: null },
    ])('reads $case', ({ messageData, expected }) => {
        expect(sessionErrorItem(messageData)).toEqual(expected);
    });
});
