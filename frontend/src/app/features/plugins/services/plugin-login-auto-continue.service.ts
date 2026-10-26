import { DOCUMENT } from '@angular/common';
import { inject, Injectable } from '@angular/core';

/** `sessionStorage` on EpicStaff's origin: the `state` of the last sign-in `/plugin-login` continued by itself. */
const AUTO_CONTINUED_STATE_KEY = 'epicstaff.pluginLogin.autoContinuedState';

/**
 * Breaks a loop between `/plugin-login` and EpicStaff's authorize endpoint. A person who is already signed in continues
 * at once, but once per sign-in: when the same sign-in (the same `state`) comes back, the authorize endpoint did not
 * accept the session this page found, and sending it round again would never end. The page then shows the login form.
 */
@Injectable({ providedIn: 'root' })
export class PluginLoginAutoContinueService {
    private readonly document = inject(DOCUMENT);

    /** `true` the first time for `state`, which it remembers; `false` when it was continued already, or cannot tell. */
    claim(state: string): boolean {
        try {
            const storage = this.document.defaultView?.sessionStorage;
            if (!storage || storage.getItem(AUTO_CONTINUED_STATE_KEY) === state) return false;
            storage.setItem(AUTO_CONTINUED_STATE_KEY, state);
            return true;
        } catch {
            // Storage blocked: without it a loop cannot be seen, so never continue by itself.
            return false;
        }
    }
}
