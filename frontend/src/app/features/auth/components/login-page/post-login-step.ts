import { InjectionToken } from '@angular/core';

/**
 * What the login page does once the person is signed in, instead of going to its `returnUrl`. Provide it on a page
 * that shows `<app-login-page />` for a purpose of its own, so the form is reused rather than copied.
 */
export interface PostLoginStep {
    continueAfterLogin(): void;
}

export const POST_LOGIN_STEP = new InjectionToken<PostLoginStep>('POST_LOGIN_STEP');
