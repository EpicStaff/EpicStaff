import { DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PasswordChangeVerifyResponse } from '@shared/models';
import { EMPTY, of, throwError } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { PasswordChangeDialogComponent } from './password-change-dialog.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('PasswordChangeDialogComponent revocation notice', () => {
    let fixture: ComponentFixture<PasswordChangeDialogComponent>;

    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        const verifyResponse: PasswordChangeVerifyResponse = { ticket: 'change-ticket', expires_in: 300 };
        TestBed.configureTestingModule({
            imports: [PasswordChangeDialogComponent],
            providers: [
                { provide: DialogRef, useValue: { close: vi.fn(), keydownEvents: EMPTY } as unknown as DialogRef },
                {
                    provide: ProfileService,
                    useValue: { requestPasswordChange: () => of(verifyResponse) } as unknown as ProfileService,
                },
                { provide: AuthService, useValue: {} as AuthService },
                { provide: ToastService, useValue: {} as ToastService },
            ],
        });
        fixture = TestBed.createComponent(PasswordChangeDialogComponent);
    });

    function normalizedText(selector: string): string | undefined {
        const element: HTMLElement = fixture.nativeElement;
        return element.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
    }

    function primaryButtonLabel(): string | undefined {
        return normalizedText('.footer app-button[type="primary"]');
    }

    it('warns that sessions end and API keys are revoked once the current password is verified', () => {
        fixture.detectChanges();
        fixture.componentInstance.verifyForm.controls.current_password.setValue('current-password');

        fixture.componentInstance.onVerify();
        fixture.detectChanges();

        expect(normalizedText('app-hint-message')).toBe(
            'Changing your password will sign you out of all other sessions and revoke all your API keys. ' +
                'Integrations using them will stop working until you create new keys.'
        );
        expect(primaryButtonLabel()).toBe('Change password');
    });

    it('does not show the notice while the current password is being verified', () => {
        fixture.detectChanges();

        expect(normalizedText('app-hint-message')).toBeUndefined();
        expect(primaryButtonLabel()).toBe('Continue');
    });
});

describe('PasswordChangeDialogComponent new password refused', () => {
    afterEach(() => vi.unstubAllGlobals());

    function submitRefused(errors: object[]): {
        fixture: ComponentFixture<PasswordChangeDialogComponent>;
        toastError: ReturnType<typeof vi.fn>;
    } {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        const toastError = vi.fn();
        const refusal = new HttpErrorResponse({ status: 400, error: { type: 'validation_error', errors } });
        TestBed.configureTestingModule({
            imports: [PasswordChangeDialogComponent],
            providers: [
                { provide: DialogRef, useValue: { close: vi.fn(), keydownEvents: EMPTY } as unknown as DialogRef },
                {
                    provide: ProfileService,
                    useValue: {
                        requestPasswordChange: () => of({ ticket: 'change-ticket', expires_in: 300 }),
                        confirmPasswordChange: () => throwError(() => refusal),
                    } as unknown as ProfileService,
                },
                { provide: AuthService, useValue: {} as AuthService },
                { provide: ToastService, useValue: { error: toastError } as unknown as ToastService },
            ],
        });
        const fixture = TestBed.createComponent(PasswordChangeDialogComponent);
        fixture.detectChanges();
        fixture.componentInstance.verifyForm.controls.current_password.setValue('current-password');
        fixture.componentInstance.onVerify();
        fixture.detectChanges();
        fixture.componentInstance.newPasswordForm.setValue({
            new_password: 'brand-new-password',
            confirm_password: 'brand-new-password',
        });

        fixture.componentInstance.onSubmit();
        fixture.detectChanges();
        return { fixture, toastError };
    }

    function error(attr: string | null, detail: string): object {
        return { code: 'invalid', detail, attr, context: null };
    }

    it('shows the reason under the new password field when the server names only that field', () => {
        const { fixture, toastError } = submitRefused([error('new_password', 'This password is too common.')]);

        const element: HTMLElement = fixture.nativeElement;
        expect(element.querySelector('form')?.textContent).toContain('This password is too common.');
        expect(toastError).not.toHaveBeenCalled();
    });

    it.each([
        [
            'an error for the whole form',
            [error('new_password', 'This password is too common.'), error(null, 'The ticket has expired.')],
            'new_password: This password is too common.; The ticket has expired.',
        ],
        ['an error for a field the dialog has no input for', [error('ticket', 'Expired.')], 'ticket: Expired.'],
    ])('says every reason in a toast when the refusal carries %s', (_case, errors, toast) => {
        const { toastError } = submitRefused(errors);

        expect(toastError).toHaveBeenCalledWith(toast);
    });
});
