import { HttpErrorResponse } from '@angular/common/http';

import { extractHttpErrorMessage } from './http-error.util';

/** Status 0: no response at all — the server is down or the connection dropped. */
export const SERVER_UNREACHABLE_MESSAGE = "The server couldn't be reached. Check your connection and try again.";

/** A 5xx whose body says nothing readable (none, or an HTML error page). */
export const SERVER_FAILED_MESSAGE = 'Something went wrong on the server. Try again or contact your administrator.';

/** A 4xx whose body says nothing readable. */
export const REQUEST_REJECTED_MESSAGE = 'The server rejected the request.';

/** Not an HTTP failure at all: an error thrown on the way, whose own message is meant for developers. */
export const UNEXPECTED_ERROR_MESSAGE = 'Something went wrong. Try again.';

/**
 * Why a request failed, to put after a heading such as "Couldn't save the flow.": the server's own message, or
 * a plain sentence when there was no response or the body names no reason. Never Angular's
 * "Http failure response for <url>: …" text, which `extractHttpErrorMessage` falls back to when the body has no
 * message.
 */
export function httpErrorReason(error: HttpErrorResponse | Error): string {
    // No status: an error thrown on the way. Its message is a developer's, so it goes to the console, not the UI.
    if (!hasHttpStatus(error)) {
        console.error(error);
        return UNEXPECTED_ERROR_MESSAGE;
    }
    if (error.status === 0) return SERVER_UNREACHABLE_MESSAGE;
    const statusMessage = error.status >= 500 ? SERVER_FAILED_MESSAGE : REQUEST_REJECTED_MESSAGE;
    // The fallback is what an HTML error page reads as; a body with no message at all gives back `error.message`.
    const message = extractHttpErrorMessage(error, statusMessage);
    if (!message || message === error.message) return statusMessage;
    return message;
}

function hasHttpStatus(error: HttpErrorResponse | Error): error is HttpErrorResponse {
    return typeof (error as Partial<HttpErrorResponse>).status === 'number';
}
