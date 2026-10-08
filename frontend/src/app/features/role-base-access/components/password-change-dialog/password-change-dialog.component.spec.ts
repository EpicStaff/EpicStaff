import { DialogRef } from '@angular/cdk/dialog';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PasswordChangeVerifyResponse } from '@shared/models';
import { of } from 'rxjs';

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
                { provide: DialogRef, useValue: { close: vi.fn() } as unknown as DialogRef },
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
