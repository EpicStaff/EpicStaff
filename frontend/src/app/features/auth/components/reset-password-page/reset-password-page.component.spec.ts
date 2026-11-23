import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { throwError } from 'rxjs';

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

describe('ResetPasswordPageComponent password refused', () => {
    afterEach(() => vi.unstubAllGlobals());

    it.each([
        [null, 'The reset link has expired.', 'The reset link has expired.'],
        ['token', 'Invalid or expired.', 'Token: Invalid or expired.'],
    ])(
        'shows an error the field cannot show (attr %j) on the page next to the field error',
        (attr, detail, shownOnPage) => {
            vi.stubGlobal('ResizeObserver', ResizeObserverStub);
            const refusal = new HttpErrorResponse({
                status: 400,
                error: {
                    type: 'validation_error',
                    errors: [
                        {
                            code: 'invalid',
                            detail: 'This password is too common.',
                            attr: 'new_password',
                            context: null,
                        },
                        { code: 'invalid', detail, attr, context: null },
                    ],
                },
            });
            TestBed.configureTestingModule({
                imports: [ResetPasswordPageComponent],
                providers: [
                    {
                        provide: ActivatedRoute,
                        useValue: { snapshot: { queryParamMap: convertToParamMap({ token: 'reset-token' }) } },
                    },
                    { provide: Router, useValue: { navigateByUrl: vi.fn() } as unknown as Router },
                    {
                        provide: AuthService,
                        useValue: { confirmResetPassword: () => throwError(() => refusal) } as unknown as AuthService,
                    },
                    { provide: ToastService, useValue: { error: vi.fn() } as unknown as ToastService },
                ],
            });
            const fixture = TestBed.createComponent(ResetPasswordPageComponent);
            fixture.detectChanges();
            fixture.componentInstance.form.setValue({ new_password: 'brand-new-password' });

            fixture.componentInstance.onSubmit();
            fixture.detectChanges();

            const element: HTMLElement = fixture.nativeElement;
            expect(element.querySelector('.server-error')?.textContent?.trim()).toBe(shownOnPage);
            expect(element.querySelector('form')?.textContent).toContain('This password is too common.');
        }
    );
});
