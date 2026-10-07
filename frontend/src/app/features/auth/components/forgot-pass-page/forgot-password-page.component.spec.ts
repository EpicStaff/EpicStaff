import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ResetPasswordResponse } from '@shared/models';
import { of } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';
import { ForgotPasswordPageComponent } from './forgot-password-page.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const RESET_DETAIL = 'If the email is registered, a reset link has been sent.';
// Differs from the client fallback so the test proves the page renders what the server sent.
const SERVER_DETAIL = 'If that address belongs to an account, reset instructions are on their way.';
const SUBMITTED_EMAIL = 'user@example.com';

describe('ForgotPasswordPageComponent result state', () => {
    let fixture: ComponentFixture<ForgotPasswordPageComponent>;
    let requestResetPassword: ReturnType<typeof vi.fn>;

    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        requestResetPassword = vi.fn();
        TestBed.configureTestingModule({
            imports: [ForgotPasswordPageComponent],
            providers: [
                { provide: Router, useValue: { navigate: vi.fn() } as unknown as Router },
                { provide: AuthService, useValue: { requestResetPassword } as unknown as AuthService },
                { provide: ToastService, useValue: { error: vi.fn() } as unknown as ToastService },
            ],
        });
        fixture = TestBed.createComponent(ForgotPasswordPageComponent);
        fixture.detectChanges();
    });

    function submitWith(response: ResetPasswordResponse): void {
        requestResetPassword.mockReturnValue(of(response));
        fixture.componentInstance.emailControl.setValue(SUBMITTED_EMAIL);
        fixture.componentInstance.onRequestReset();
        fixture.detectChanges();
    }

    function normalizedText(selector: string): string | undefined {
        const element: HTMLElement = fixture.nativeElement;
        return element.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
    }

    it('explains in the request form that a link is sent only when an account exists', () => {
        expect(normalizedText('.hint')).toBe(
            "If an account exists for this email, we'll send you a link to reset your password."
        );
    });

    it('shows the server wording, which does not reveal whether the account exists, when SMTP is configured', () => {
        submitWith({ detail: SERVER_DETAIL, smtp_configured: true });

        expect(requestResetPassword).toHaveBeenCalledWith({ email: SUBMITTED_EMAIL });
        expect(normalizedText('.title')).toBe('Check email');
        expect(normalizedText('.subtitle')).toBe(SERVER_DETAIL);
        expect(fixture.nativeElement.textContent).not.toContain('We have sent');
        expect(fixture.nativeElement.textContent).not.toContain(SUBMITTED_EMAIL);
    });

    it.each([
        ['missing', undefined],
        ['null', null],
        ['empty', ''],
        ['blank', '   '],
    ])('falls back to the account-neutral wording when the server detail is %s', (_case, detail) => {
        submitWith({ detail, smtp_configured: true } as ResetPasswordResponse);

        expect(normalizedText('.title')).toBe('Check email');
        expect(normalizedText('.subtitle')).toBe(RESET_DETAIL);
    });

    it('tells the user to contact an administrator when the server has no SMTP configured', () => {
        submitWith({ detail: RESET_DETAIL, smtp_configured: false });

        expect(normalizedText('.title')).toBe('Reset unavailable');
        expect(normalizedText('.subtitle')).toBe(
            "Password reset by email isn't available on this server. Ask your administrator to reset your password."
        );
        expect(fixture.nativeElement.textContent).not.toContain(SUBMITTED_EMAIL);
        expect(fixture.nativeElement.textContent).not.toContain('We have sent');
        expect(normalizedText('.back-link')).toBe('Back to Login');
    });

    it('treats a response without the SMTP flag as unavailable rather than claiming a link was sent', () => {
        submitWith({ detail: RESET_DETAIL } as ResetPasswordResponse);

        expect(normalizedText('.title')).toBe('Reset unavailable');
        expect(fixture.nativeElement.textContent).not.toContain('We have sent');
    });
});
