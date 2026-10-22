import { GATEWAY_DENY_HEADER, GATEWAY_DENY_REASONS, type GatewayDenyReason } from './login-protocol.js';

/** A refusal EpicStaff's gateway answered itself, in front of the plugin's own API. */
export interface GatewayRefusal {
    reason: GatewayDenyReason;
    /** From `Retry-After`, when the gateway sent a number of seconds; `null` otherwise. */
    retryAfterSeconds: number | null;
}

/** `Retry-After` as a whole number of seconds; the gateway never sends the date form. */
const RETRY_AFTER_SECONDS = /^[0-9]{1,9}$/;

/**
 * What EpicStaff's gateway refused, from `X-EpicStaff-Gateway-Deny` and `Retry-After`; `null` for a response that
 * passed the gateway (the plugin's own answer), or that names a reason this SDK does not know.
 */
export function gatewayRefusal(response: Response): GatewayRefusal | null {
    const header = response.headers.get(GATEWAY_DENY_HEADER);
    const reason = GATEWAY_DENY_REASONS.find((known) => known === header);
    if (reason === undefined) return null;
    const retryAfter = response.headers.get('retry-after')?.trim() ?? '';
    return { reason, retryAfterSeconds: RETRY_AFTER_SECONDS.test(retryAfter) ? Number(retryAfter) : null };
}

/** A response that EpicStaff's gateway let through to the plugin: it has no refusal header at all. */
export function passedGateway(response: Response): boolean {
    return !response.headers.has(GATEWAY_DENY_HEADER);
}
