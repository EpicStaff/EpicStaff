import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';
import { ResetPasswordPageComponent } from './reset-password-page.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('ResetPasswordPageComponent revocation notice', () => {
    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            imports: [ResetPasswordPageComponent],
            providers: [
                {
                    provide: ActivatedRoute,
                    useValue: { snapshot: { queryParamMap: convertToParamMap({ token: 'reset-token' }) } },
                },
                { provide: Router, useValue: { navigateByUrl: vi.fn() } as unknown as Router },
                { provide: AuthService, useValue: {} as AuthService },
                { provide: ToastService, useValue: {} as ToastService },
            ],
        });
    });

    it('warns that sessions end and API keys are revoked before the new password is saved', () => {
        const fixture = TestBed.createComponent(ResetPasswordPageComponent);
        fixture.detectChanges();

        const element: HTMLElement = fixture.nativeElement;
        const notice = element.querySelector('app-hint-message')?.textContent?.replace(/\s+/g, ' ').trim();

        expect(notice).toBe(
            'Setting a new password will sign you out everywhere and revoke all your API keys. ' +
                'Integrations using them will stop working until you create new keys.'
        );
    });
});
