/**
 * Login protocol 1, EpicStaff's side: the pages EpicStaff's authorize endpoint sends a person to while a plugin page
 * signs them in, and the request those pages continue. The single source is `plugin-sdk/contracts/login-protocol.json`;
 * `plugin-login-protocol.contract.spec.ts` asserts these equal it.
 */

export const PLUGIN_LOGIN_PATHS = {
    /** EpicStaff's authorize endpoint; `continue` always points at it. */
    authorize: '/api/auth/plugin-authorize/',
    /** The login form, then the authorize request again. */
    loginContinue: '/plugin-login',
    /** The organization chooser, then the authorize request with `org`. */
    chooseOrg: '/plugin-choose-org',
} as const;

/** The query parameter of both pages that carries the authorize request to continue. */
export const PLUGIN_LOGIN_CONTINUE_PARAMETER = 'continue';

/** The authorize parameters the pages read or set. */
export const PLUGIN_AUTHORIZE_PARAMETERS = {
    plugin: 'plugin',
    state: 'state',
    org: 'org',
    /** Only a silent sign-in sends it, and EpicStaff never sends a person to these pages for one. */
    prompt: 'prompt',
} as const;

/** `continue` as EpicStaff's authorize endpoint rebuilds it: the authorize path and a plain query. */
export const PLUGIN_LOGIN_CONTINUE_PATTERN = /^\/api\/auth\/plugin-authorize\/\?[A-Za-z0-9._~%=&+-]{1,4000}$/;
