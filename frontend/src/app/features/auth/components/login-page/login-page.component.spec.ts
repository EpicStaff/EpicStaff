import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { NEVER, of, throwError } from 'rxjs';

import { AuthService } from '../../../../services/auth/auth.service';
import { ToastService } from '../../../../services/notifications';
import { LoginPageComponent } from './login-page.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const THROTTLE_MESSAGE = 'Request was throttled. Expected available in 58 seconds.';

function throttledResponse(headers: Record<string, string>, message: string | null): HttpErrorResponse {
    return new HttpErrorResponse({
        status: 429,
        statusText: 'Too Many Requests',
        headers: new HttpHeaders(headers),
        error: message === null ? null : { status_code: 429, code: 'throttled', message },
    });
}

describe('LoginPageComponent throttled login', () => {
    let fixture: ComponentFixture<LoginPageComponent>;
    let login: ReturnType<typeof vi.fn>;

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        login = vi.fn();
        TestBed.configureTestingModule({
            imports: [LoginPageComponent],
            providers: [
                { provide: Router, useValue: { navigate: vi.fn(), navigateByUrl: vi.fn() } as unknown as Router },
                {
                    provide: ActivatedRoute,
                    useValue: { snapshot: { queryParamMap: convertToParamMap({}) } } as unknown as ActivatedRoute,
                },
                {
                    provide: AuthService,
                    useValue: { getStatus: () => of({ needs_setup: false }), login } as unknown as AuthService,
                },
                { provide: ToastService, useValue: { info: vi.fn() } as unknown as ToastService },
            ],
        });
        fixture = TestBed.createComponent(LoginPageComponent);
        fixture.detectChanges();
    });

    function fillValidCredentials(): void {
        fixture.componentInstance.form.setValue({
            email: 'user@example.com',
            password: 'password-123',
            rememberMe: false,
        });
    }

    function pressEnterInForm(): void {
        const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
        form.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        fixture.detectChanges();
    }

    function submitRejectedWith(error: HttpErrorResponse): void {
        login.mockReturnValue(throwError(() => error));
        fillValidCredentials();
        fixture.componentInstance.onSubmit();
        fixture.detectChanges();
    }

    function serverErrorText(): string | undefined {
        const element: HTMLElement = fixture.nativeElement;
        return element.querySelector('.server-error')?.textContent?.replace(/\s+/g, ' ').trim();
    }

    function isLoginButtonDisabled(): boolean {
        const element: HTMLElement = fixture.nativeElement;
        return element.querySelector<HTMLButtonElement>('app-button button')!.disabled;
    }

    it('counts down the wait from Retry-After and blocks resubmitting until it ends', () => {
        submitRejectedWith(throttledResponse({ 'Retry-After': '58' }, THROTTLE_MESSAGE));

        expect(serverErrorText()).toBe('Too many login attempts. Please try again in 58s.');
        expect(isLoginButtonDisabled()).toBe(true);

        vi.advanceTimersByTime(3000);
        fixture.detectChanges();
        expect(serverErrorText()).toBe('Too many login attempts. Please try again in 55s.');

        fixture.componentInstance.onSubmit();
        expect(login).toHaveBeenCalledTimes(1);

        vi.advanceTimersByTime(55_000);
        fixture.detectChanges();
        expect(fixture.componentInstance.throttleSecondsLeft()).toBe(0);
        expect(serverErrorText()).toBeUndefined();
        expect(isLoginButtonDisabled()).toBe(false);
    });

    it('shows the server message when the response has no Retry-After', () => {
        submitRejectedWith(throttledResponse({}, THROTTLE_MESSAGE));

        expect(fixture.componentInstance.throttleSecondsLeft()).toBe(0);
        expect(serverErrorText()).toBe(THROTTLE_MESSAGE);
    });

    it('shows a generic throttle message when Retry-After is unreadable and the body has no message', () => {
        submitRejectedWith(throttledResponse({ 'Retry-After': 'later' }, null));

        expect(serverErrorText()).toBe('Too many login attempts. Please try again later.');
    });

    it('sends one request when Enter is pressed again while the first login is still pending', () => {
        login.mockReturnValue(NEVER);
        fillValidCredentials();

        pressEnterInForm();
        pressEnterInForm();

        expect(login).toHaveBeenCalledTimes(1);
        expect(fixture.componentInstance.loading()).toBe(true);
    });
});
