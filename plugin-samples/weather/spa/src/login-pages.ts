import { type CompletePopupOutcome, type PluginLogin, type PopupResult } from '@epicstaff/plugin-sdk';

import { button, element, facts } from './dom';

export const WHO_AM_I_PATH = '/me';
export const CONNECT_PATH = '/connect';
/** Where the demo provider sends the popup back to (fixed by the sample's backend). */
export const OAUTH_CALLBACK_PATH = '/oauth-demo/callback';
/** The sample backend's relay: the popup posts the provider's parameters, the page polls for them. */
export const POPUP_RELAY_PATH = '/api/popup-relay';

/** What `GET /api/whoami` answers: the gateway context the backend received. */
export interface WhoAmI {
    mode: string;
    user: { id: number; email: string; name: string };
    org: { id: number; name: string };
    permissions: string[];
    request: { method: string; path: string };
}

export type WhoAmIState =
    | { status: 'loading' }
    | { status: 'loaded'; body: WhoAmI }
    | { status: 'failed'; message: string };

export type ConnectState =
    | { status: 'idle' }
    | { status: 'waiting'; label: string }
    | { status: 'done'; label: string; result: PopupResult }
    | { status: 'failed'; label: string; message: string };

/**
 * The page for every login state but `signed-in`, or `null` when signed in. Inside EpicStaff an ended session offers
 * "Sign in again"; on its own the SDK has already gone to EpicStaff's login.
 */
export function renderLoginState(login: PluginLogin, pluginName: string): HTMLElement[] | null {
    switch (login.state) {
        case 'signed-in':
            return null;
        case 'idle':
        case 'signing-in':
            return [element('p', 'muted', 'Signing in…')];
        case 'access-denied':
            return [element('p', 'note', `You do not have access to ${pluginName} in this organization.`)];
        case 'session-ended':
            return [
                element('p', 'note', 'Your EpicStaff session has ended.'),
                button('Sign in again', () => void login.signIn()),
            ];
        case 'failed':
            return [
                element('p', 'note note--error', `Could not sign in: ${login.error?.message ?? 'unknown error'}`),
                button('Try again', () => void login.signIn()),
            ];
    }
}

/** The "Who am I" page: what the backend's gateway context says, the token's expiry, and "Renew now". */
export function renderWhoAmI(login: PluginLogin, whoAmI: WhoAmIState, onRenew: () => void): HTMLElement[] {
    const session = login.session;
    const expiry = session
        ? `${new Date(session.expiresAt).toLocaleTimeString()} (in ${Math.max(
              0,
              Math.round((session.expiresAt - Date.now()) / 1000)
          )} s)`
        : 'No token';
    const renew = button('Renew now', onRenew);
    renew.classList.add('button--secondary');
    const content: HTMLElement[] = [];
    if (whoAmI.status === 'loading') content.push(element('p', 'muted', 'Asking the backend…'));
    if (whoAmI.status === 'failed') content.push(element('p', 'note note--error', whoAmI.message));
    if (whoAmI.status === 'loaded') {
        const { user, org, permissions, mode, request } = whoAmI.body;
        content.push(
            facts([
                ['Name', user.name],
                ['Email', user.email],
                ['Organization', `${org.name} (${org.id})`],
                ['Permissions', JSON.stringify(permissions)],
                ['Context mode', mode],
                ['Request', `${request.method} ${request.path}`],
            ])
        );
    }
    content.push(facts([['Token expires', expiry]]), renew);
    return content;
}

/**
 * The "Connect" page: a demo of an external provider's sign-in in a popup. The second button makes the provider send
 * `Cross-Origin-Opener-Policy`, which cuts the popup off from this page, so the result has to come back through the
 * relay.
 */
export function renderConnect(state: ConnectState, onConnect: (severOpener: boolean) => void): HTMLElement[] {
    const intro = element(
        'p',
        'muted',
        'Opens the demo provider in a popup, the way a plugin would open Google’s sign-in, and shows what it sent back.'
    );
    const actions = element('div', 'actions');
    actions.append(
        button('Connect', () => onConnect(false)),
        button('Connect — provider severs the opener', () => onConnect(true))
    );
    const content: HTMLElement[] = [intro, actions];
    if (state.status === 'waiting') content.push(element('p', 'muted', `${state.label}: waiting for the popup…`));
    if (state.status === 'failed') content.push(element('p', 'note note--error', `${state.label}: ${state.message}`));
    if (state.status === 'done') {
        content.push(
            element('p', null, `${state.label}: the provider answered.`),
            facts([
                ['Came back through', state.result.via === 'opener' ? 'The popup’s opener' : 'The relay'],
                ...Object.entries(state.result.params).map(([name, value]): [string, string] => [name, value]),
            ])
        );
    }
    return content;
}

/** What the provider's return page shows while and after it hands the result back. */
export function renderPopupOutcome(outcome: CompletePopupOutcome | null, pluginName: string): HTMLElement[] {
    if (outcome === null) return [element('p', 'muted', 'Finishing…')];
    switch (outcome.status) {
        case 'posted':
        case 'relayed':
            return [element('p', null, 'Done — you can close this window.')];
        case 'signing-in':
            return [element('p', 'muted', 'Signing in…')];
        case 'no-opener':
            return [element('p', 'note', `This window lost its connection to ${pluginName}. Close it and try again.`)];
        case 'invalid':
            return [element('p', 'note', 'There is nothing to finish here.')];
        case 'access-denied':
            return [element('p', 'note', `You do not have access to ${pluginName} in this organization.`)];
        case 'failed':
            return [element('p', 'note note--error', `Could not finish: ${outcome.error.message}`)];
    }
}
