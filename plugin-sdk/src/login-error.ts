/** Why a sign-in or a popup hand-off could not go on. */
export type PluginLoginErrorCode =
    /** The page is not a secure context, so the Web Crypto API that PKCE needs is missing. */
    | 'insecure_context'
    /** The platform config offers no sign-in (`login: null`): the plugin has no backend. */
    | 'login_unavailable'
    /** `sessionStorage` is not available, so an interactive sign-in cannot come back to the page. */
    | 'storage_unavailable'
    /** The callback page brought back neither a code nor an error EpicStaff uses. */
    | 'callback_failed'
    /** EpicStaff's token endpoint refused the code or could not be reached. */
    | 'exchange_failed'
    /** The token endpoint answered with something that is not a plugin login token. */
    | 'invalid_token_response'
    /** `openPopup` or `completePopup` got a `state` that is not `<org id>.<random>`. */
    | 'invalid_popup_state'
    /** `openPopup` got an address that is not `http:` or `https:` (`javascript:`, `data:`, …). */
    | 'invalid_popup_url'
    /** The browser blocked the popup: `openPopup` was not called from a click or a key press. */
    | 'popup_blocked'
    /** No result arrived in time. */
    | 'popup_timeout'
    /** The plugin's relay refused the provider's parameters. */
    | 'relay_failed'
    /** `close()` stopped the operation. */
    | 'closed';

export class PluginLoginError extends Error {
    override readonly name = 'PluginLoginError';
    readonly code: PluginLoginErrorCode;

    constructor(code: PluginLoginErrorCode, message: string) {
        super(message);
        this.code = code;
    }
}

export function describeError(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}
