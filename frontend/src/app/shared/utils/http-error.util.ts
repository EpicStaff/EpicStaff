import { HttpErrorResponse } from '@angular/common/http';
import { ApiErrorDetail, ApiErrorResponse, HttpStatus } from '@shared/models';

/**
 * Every error a response body reports, as `{code, detail, attr, context}` items, read from the `{type, errors}`
 * envelope. Any other body (a proxy's HTML page, plain text, an empty body) gives an empty list.
 */
export function toApiErrors(body: unknown): ApiErrorDetail[] {
    return isEnvelope(body) ? readEnvelope(body) : [];
}

/**
 * Extracts a human-readable message from an HttpErrorResponse
 */
export function extractHttpErrorMessage(err: HttpErrorResponse, fallback?: string): string {
    const serverMessage = readServerMessage(err?.error);
    if (serverMessage) return serverMessage;

    // A body that is not JSON: a plain-text reason is shown as it is, an HTML page never.
    if (typeof err?.error === 'string' && err.error) {
        if (!HTML_DOCUMENT.test(err.error)) return simplifyKnownMessage(err.error);
        return fallback ?? (err.status >= 500 ? `Server error (${err.status})` : `Request failed (${err.status})`);
    }
    return err?.message || (fallback ?? 'Unknown error');
}

/**
 * Why a request failed, for the end of a "Couldn't …" toast: the server's own reason when it gave one,
 * otherwise what kind of failure it was. Angular's own `message` ("Http failure response for …") is never shown.
 */
export function httpFailureReason(error: unknown): string {
    // A failure thrown in the app before any request was sent says nothing about the server.
    if (!(error instanceof HttpErrorResponse)) return 'Something went wrong.';
    if (error.status === 0) return "The server couldn't be reached.";
    // A success status that still failed: the body (an HTML page, say) couldn't be parsed.
    if (error.status < 400) return "The server's response couldn't be read.";
    const genericReason =
        error.status >= 500 ? 'Something went wrong on the server.' : 'The server rejected the request.';
    const reason = extractHttpErrorMessage(error, genericReason);
    return reason === error.message ? genericReason : reason;
}

/**
 * What the server said went wrong, in words (every error it reports, joined); null when it said nothing readable, so
 * the caller can put its own text instead. Unlike {@link extractHttpErrorMessage}, never Angular's own message.
 */
export function extractServerMessage(error: unknown): string | null {
    return error instanceof HttpErrorResponse ? readServerMessage(error.error) : null;
}

/** Every error a failed request reports; empty for anything that is not an HTTP error with a body. */
export function extractApiErrors(error: unknown): ApiErrorDetail[] {
    return error instanceof HttpErrorResponse ? toApiErrors(error.error) : [];
}

/**
 * The errors of a validation failure (400 or 422) that names at least one field, for a form to show under its
 * fields (errors with `attr: null` go to the whole form). Empty for any other failure, which the caller says as a
 * whole instead.
 */
export function extractFieldErrors(error: unknown): ApiErrorDetail[] {
    if (!(error instanceof HttpErrorResponse) || !VALIDATION_STATUSES.includes(error.status)) return [];
    const errors = toApiErrors(error.error);
    return errors.some((item) => item.attr !== null) ? errors : [];
}

/**
 * The code of the first error a failed request reports; null when the body names none (`unknown`), and for anything
 * that is not an HTTP error with a body.
 */
export function extractErrorCode(error: unknown): string | null {
    const code = firstApiError(error)?.code;
    return code && code !== UNKNOWN_ERROR_CODE ? code : null;
}

/** The structured data of the first error a failed request reports; null when it carries none. */
export function extractErrorContext(error: unknown): Record<string, unknown> | null {
    return firstApiError(error)?.context ?? null;
}

/**
 * The reasons a validation error (400 or 422) gives for one field, matched on the error's `attr`.
 * Empty when the field is not named.
 */
export function extractFieldErrorMessages(err: HttpErrorResponse, field: string): string[] {
    if (!VALIDATION_STATUSES.includes(err.status)) return [];
    return toApiErrors(err.error)
        .filter((error) => error.attr === field)
        .map((error) => error.detail)
        .filter(Boolean);
}

/** What a session error message reports, read from its `error` item; null when it carries none. */
export function sessionErrorItem(messageData: { error?: unknown }): ApiErrorDetail | null {
    return toApiErrorDetail(messageData.error);
}

/** Dedupe messages, cap to 3, and append "…and N more" for the remainder. */
export function joinErrorMessages(messages: readonly string[]): string {
    const unique = Array.from(new Set(messages));
    const MAX = 3;
    if (unique.length <= MAX) return unique.join('; ');
    return `${unique.slice(0, MAX).join('; ')}; …and ${unique.length - MAX} more`;
}

const HTML_DOCUMENT = /^\s*<(!doctype|html)/i;
const VALIDATION_STATUSES: number[] = [HttpStatus.BadRequest, HttpStatus.UnprocessableEntity];
/** The code of an error that names none, as the envelope itself puts it. */
const UNKNOWN_ERROR_CODE = 'unknown';
// Keys DRF and Django name a whole-form error with; an error under one belongs to no single field.
const NON_FIELD_KEYS: ReadonlySet<string> = new Set(['non_field_errors', '__all__']);

type JsonObject = Record<string, unknown>;

function firstApiError(error: unknown): ApiErrorDetail | undefined {
    return extractApiErrors(error)[0];
}

function readServerMessage(body: unknown): string | null {
    const messages = toApiErrors(body)
        .map(({ attr, detail }) => (attr && detail ? `${attr}: ${detail}` : detail))
        .filter(Boolean);
    return messages.length ? joinErrorMessages(messages.map(simplifyKnownMessage)) : null;
}

function isEnvelope(body: unknown): body is ApiErrorResponse {
    return isObject(body) && typeof body['type'] === 'string' && Array.isArray(body['errors']);
}

/** The items of the envelope; one that is not a `{code, detail, attr, context}` object is skipped. */
function readEnvelope(body: ApiErrorResponse): ApiErrorDetail[] {
    return body.errors.flatMap((item: unknown) => {
        const error = toApiErrorDetail(item);
        return error ? [error] : [];
    });
}

function toApiErrorDetail(value: unknown): ApiErrorDetail | null {
    if (!isObject(value) || typeof value['detail'] !== 'string') return null;
    const code = value['code'];
    const context = value['context'];
    return {
        code: typeof code === 'string' && code ? code : UNKNOWN_ERROR_CODE,
        detail: value['detail'],
        attr: toFieldAttr(value['attr']),
        context: isObject(context) ? context : null,
    };
}

/**
 * The field an error's `attr` names, as a dotted path; null when it names none. A whole-form key at its end
 * (`non_field_errors`, `__all__`) is about the item before it, so the error belongs to that item as a whole.
 */
function toFieldAttr(attr: unknown): string | null {
    if (typeof attr !== 'string' || !attr) return null;
    const path = attr.split('.');
    if (NON_FIELD_KEYS.has(path[path.length - 1])) path.pop();
    return path.length ? path.join('.') : null;
}

function isObject(value: unknown): value is JsonObject {
    return value != null && typeof value === 'object' && !Array.isArray(value);
}

const UNDECLARED_SECRET_CALLS =
    /Code calls ((?:get_secret\([^)]*\)(?:,\s*)?)+) but (?:that secret is|those secrets are) not selected for this node\./;
const GET_SECRET_NAME = /get_secret\(\s*["']([^"']*)["']/g;

function simplifyKnownMessage(raw: string): string {
    const match = raw.match(UNDECLARED_SECRET_CALLS);
    if (!match) return raw;

    const names = [...match[1].matchAll(GET_SECRET_NAME)].map((m) => m[1]);
    if (!names.length) return raw;

    const isPlural = names.length > 1;
    const quotedNames = names.map((name) => `"${name}"`).join(', ');
    return `Secret${isPlural ? 's' : ''} ${quotedNames} ${isPlural ? 'are' : 'is'} not declared for this node.`;
}
