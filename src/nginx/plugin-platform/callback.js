// EpicStaff's sign-in callback for plugin pages, served on every plugin host as
// /.well-known/epicstaff/callback.js and loaded by callback.html and silent-callback.html.
//
// EpicStaff's authorize endpoint redirects here with "#code=…&state=…" or "#error=…&state=…".
// - callback.html (an interactive sign-in): keeps the answer in sessionStorage for the plugin page
//   that started the sign-in, and returns to that page's address.
// - silent-callback.html (inside the page's hidden frame): posts the answer to the page that
//   framed it, on this origin only.
//
// Hand-written ES2020 and served as committed: no build step, no inline script, no network.
// The values below mirror plugin-sdk/contracts/login-protocol.json; plugin-sdk's tests run this
// file against it.
(function epicstaffLoginCallback() {
    'use strict';

    const PROTOCOL = 1;
    const LOGIN_RESULT_MESSAGE = 'es:login-result';
    const PENDING_KEY = 'epicstaff.login.pending';
    const RESULT_KEY = 'epicstaff.login.result';
    const PENDING_MAX_AGE_MS = 600 * 1000;
    const CALLBACK_ERRORS = ['login_required', 'access_denied', 'interaction_required', 'temporarily_unavailable'];
    const STATE_PATTERN = /^[A-Za-z0-9_-]{43,128}$/;
    const CODE_PATTERN = /^[A-Za-z0-9_-]{43}$/;
    const RETURN_PATH_PATTERN = /^\/(?![/\\])[!-~]{0,2047}$/;

    const page = window;
    const fragment = new URLSearchParams(page.location.hash.slice(1));
    // The code must not stay in the address or in the history entry.
    page.history.replaceState(null, '', page.location.pathname);

    const state = fragment.get('state');
    const answer = readAnswer(fragment.get('code'), fragment.get('error'));

    if (page.document.documentElement.getAttribute('data-callback') === 'silent') {
        handOverToFramingPage();
    } else {
        returnToPage();
    }

    /** A known error wins over a code; a code must have the code's shape. `{}` when there is neither. */
    function readAnswer(code, error) {
        if (error !== null && CALLBACK_ERRORS.includes(error)) return { error };
        if (code !== null && CODE_PATTERN.test(code)) return { code };
        return {};
    }

    function handOverToFramingPage() {
        // Top level, nobody is waiting for the answer.
        if (page.parent === page || state === null || !STATE_PATTERN.test(state)) return;
        // Never "*": the answer is for a page of this plugin's own origin only.
        page.parent.postMessage(
            { type: LOGIN_RESULT_MESSAGE, protocol: PROTOCOL, state, ...answer },
            page.location.origin
        );
    }

    function returnToPage() {
        let target = '/';
        try {
            const pending = JSON.parse(page.sessionStorage.getItem(PENDING_KEY) || 'null');
            if (isPendingFor(pending, state)) {
                page.sessionStorage.setItem(RESULT_KEY, JSON.stringify({ state, ...answer }));
                if (isOwnPath(pending.return_path)) target = pending.return_path;
            }
        } catch (error) {
            // No storage, or a pending entry that is not JSON: go to the plugin's start page.
            target = '/';
        }
        // replace, never assign: inside EpicStaff's frame a new entry would land in EpicStaff's history.
        page.location.replace(target);
    }

    function isPendingFor(pending, answeredState) {
        return (
            pending !== null &&
            typeof pending === 'object' &&
            typeof pending.state === 'string' &&
            STATE_PATTERN.test(pending.state) &&
            pending.state === answeredState &&
            typeof pending.created_at === 'number' &&
            Date.now() - pending.created_at < PENDING_MAX_AGE_MS
        );
    }

    /** A path on this origin only: never "//host", "/\host", a scheme, or anything outside printable ASCII. */
    function isOwnPath(path) {
        if (typeof path !== 'string' || !RETURN_PATH_PATTERN.test(path)) return false;
        try {
            return new URL(path, page.location.origin).origin === page.location.origin;
        } catch (error) {
            return false;
        }
    }
})();
