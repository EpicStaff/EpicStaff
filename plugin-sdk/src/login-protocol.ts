/**
 * EpicStaff login protocol 1: how a plugin page signs a person in through EpicStaff.
 *
 * The page sends the browser to EpicStaff's authorize endpoint with a PKCE challenge and a `state`; EpicStaff answers
 * on the platform callback page of the plugin's own origin with a single-use code in the fragment; the page exchanges
 * the code for a short-lived plugin login token, which it sends only to its own `/api/`.
 *
 * `contracts/login-protocol.json` is the single source of these values; a test asserts the constants below equal it.
 */

export const LOGIN_PROTOCOL_VERSION = 1;

export const LOGIN_PATHS = {
    /** On EpicStaff's origin. */
    authorize: '/api/auth/plugin-authorize/',
    /** On EpicStaff's origin. */
    token: '/api/auth/plugin-token/',
    /** On the plugin's origin: stores the answer and returns to the page. */
    callback: '/.well-known/epicstaff/callback.html',
    /** On the plugin's origin: hands the answer to the page that framed it. */
    silentCallback: '/.well-known/epicstaff/silent-callback.html',
    /** On the plugin's origin: the script both callback pages load. */
    callbackScript: '/.well-known/epicstaff/callback.js',
    /** On EpicStaff's origin: the login form, which then continues the authorize request. */
    loginContinue: '/plugin-login',
    /** On EpicStaff's origin: the organization chooser, which then continues the authorize request. */
    chooseOrg: '/plugin-choose-org',
} as const;

/** Every parameter the authorize endpoint takes, in the order the SDK sends them. Any other one is refused. */
export const LOGIN_AUTHORIZE_PARAMETERS = [
    'plugin',
    'state',
    'code_challenge',
    'code_challenge_method',
    'org',
    'prompt',
] as const;

export const LOGIN_CODE_CHALLENGE_METHOD = 'S256';

export const LOGIN_PROMPT_VALUES = ['none'] as const;

/** What the callback fragment's `error` may be (OAuth vocabulary, not API error codes). */
export const LOGIN_CALLBACK_ERRORS = ['login_required', 'access_denied', 'interaction_required'] as const;

export type LoginCallbackError = (typeof LOGIN_CALLBACK_ERRORS)[number];

export const LOGIN_MESSAGE_TYPES = {
    /** The silent callback page → the page that framed it. */
    loginResult: 'es:login-result',
    /** A popup's return page → the page that opened it. */
    popupResult: 'es:popup-result',
} as const;

/** `sessionStorage` keys on the plugin's origin. */
export const LOGIN_STORAGE_KEYS = {
    /** The interactive login under way: `state`, verifier, return path, org, creation time. */
    pending: 'epicstaff.login.pending',
    /** The callback page's answer for the pending login. */
    result: 'epicstaff.login.result',
    /** A popup's provider parameters while the popup signs in to hand them to the relay. */
    popup: 'epicstaff.popup.result',
} as const;

/**
 * `sessionStorage` key of the organization id of the last token in this tab: the org hint when the page runs on its
 * own. Only the SDK reads it, so it is not part of the shared contract file.
 */
export const LOGIN_ORG_STORAGE_KEY = 'epicstaff.login.org';

export const LOGIN_PATTERNS = {
    state: /^[A-Za-z0-9_-]{43,128}$/,
    code: /^[A-Za-z0-9_-]{43}$/,
    codeChallenge: /^[A-Za-z0-9_-]{43}$/,
    codeVerifier: /^[A-Za-z0-9._~-]{43,128}$/,
    /** EpicStaff's `continue` parameter: the authorize request, rebuilt by EpicStaff. */
    continue: /^\/api\/auth\/plugin-authorize\/\?[A-Za-z0-9._~%=&+-]{1,4000}$/,
    /** Where the callback page returns to: a path on the plugin's own origin, printable ASCII, never `//` or `/\`. */
    returnPath: /^\/(?![/\\])[!-~]{0,2047}$/,
    /** `<org id>.<random>`: the `state` a plugin gives an external provider, see `createPopupState`. */
    popupState: /^[1-9][0-9]{0,9}\.[A-Za-z0-9_-]{22,64}$/,
} as const;

export const LOGIN_LIMITS = {
    /** How long an authorization code can be exchanged. */
    codeTtlSeconds: 60,
    /** How long a plugin login token is valid. */
    tokenLifetimeSeconds: 900,
    /** How long before expiry the SDK renews the token. */
    renewBeforeExpirySeconds: 60,
    /** How long a silent login may take before it counts as `login_required`. */
    silentTimeoutMs: 10_000,
    /** How old a pending interactive login may be when its answer arrives. */
    pendingMaxAgeSeconds: 600,
    /** How often `openPopup` asks the plugin's relay for the result. */
    popupRelayPollMs: 2000,
    /** How long `openPopup` waits for a result. */
    popupRelayTimeoutSeconds: 600,
} as const;

/**
 * The header EpicStaff's gateway sets on every refusal it answers itself, in front of the plugin's `/api/`; a plugin
 * backend can never set it (the gateway removes it from the plugin's responses). It tells a gateway refusal from the
 * plugin's own 401 or 403. Readable by the page: the request goes to the page's own origin.
 */
export const GATEWAY_DENY_HEADER = 'X-EpicStaff-Gateway-Deny';

/** The values of {@link GATEWAY_DENY_HEADER}. */
export const GATEWAY_DENY_REASONS = [
    'login',
    'forbidden',
    'not_found',
    'rate_limited',
    'too_large',
    'unavailable',
] as const;

export type GatewayDenyReason = (typeof GATEWAY_DENY_REASONS)[number];
