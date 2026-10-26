import type { LoginState, PluginAvailability, PluginLogin } from '@epicstaff/plugin-sdk';

/** How often a page opened on its own checks whether Weather is back: the gateway's `Retry-After`. */
export const MAINTENANCE_RETRY_MS = 30_000;

/** A route behind the sign-in, so its answer is the one the person's organization gets. */
export const AVAILABILITY_PROBE_PATH = '/api/whoami';

/** Sign-in outcomes that say more than maintenance does: the page shows them instead. */
const OUTCOMES_OVER_MAINTENANCE: readonly LoginState[] = ['access-denied', 'session-ended', 'failed'];

/**
 * Whether the page says "Weather is being updated" itself: only when it runs on its own (inside EpicStaff, EpicStaff
 * shows its own panel instead of the page), and not once the sign-in was denied, ended or failed: that is what the
 * person needs to see then.
 */
export function showsMaintenance(framed: boolean, availability: PluginAvailability, state: LoginState): boolean {
    return !framed && availability === 'maintenance' && !OUTCOMES_OVER_MAINTENANCE.includes(state);
}

/**
 * Checks whether Weather is back: signs in again when the sign-in was refused for maintenance, then asks the backend
 * once; the SDK's `availability` follows the answer.
 */
export async function checkAvailabilityAgain(login: Pick<PluginLogin, 'state' | 'renew' | 'fetch'>): Promise<void> {
    if (login.state === 'maintenance') await login.renew();
    if (login.state === 'signed-in') await login.fetch(AVAILABILITY_PROBE_PATH);
}
