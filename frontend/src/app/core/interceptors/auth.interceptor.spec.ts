// Side-effect import: AuthService's dependency graph reads the `validationErrors` augmentation this module declares
// (see forbidden.interceptor.spec.ts), so without it the spec program fails to type-check.
import './validation-errors.interceptor';

import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { AuthService } from '../../services/auth/auth.service';
import { authInterceptor } from './auth.interceptor';

describe('authInterceptor', () => {
    let httpClient: HttpClient;
    let httpMock: HttpTestingController;
    let refreshResult: Observable<string | null>;
    let logout: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        refreshResult = of('fresh-token');
        logout = vi.fn();
        const authService = {
            getAccessToken: () => 'stale-token',
            refreshToken: () => refreshResult,
            removeTokenAndNavToLogin: logout,
        };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([authInterceptor])),
                provideHttpClientTesting(),
                { provide: AuthService, useValue: authService as unknown as AuthService },
            ],
        });
        httpClient = TestBed.inject(HttpClient);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function requestStatus(): () => number | 'ok' | null {
        let outcome: number | 'ok' | null = null;
        httpClient.get('/chat/operator/v1/inbox/badges').subscribe({
            next: () => (outcome = 'ok'),
            error: (err: HttpErrorResponse) => (outcome = err.status),
        });
        return () => outcome;
    }

    function rejectWith401(): void {
        httpMock.expectOne('/chat/operator/v1/inbox/badges').flush(null, { status: 401, statusText: 'Unauthorized' });
    }

    it('retries a 401 once with the refreshed token', () => {
        const outcome = requestStatus();
        rejectWith401();
        const retry = httpMock.expectOne('/chat/operator/v1/inbox/badges');
        expect(retry.request.headers.get('Authorization')).toBe('Bearer fresh-token');
        retry.flush({});
        expect(outcome()).toBe('ok');
        expect(logout).not.toHaveBeenCalled();
    });

    it('keeps the session when the refresh works but the retried request is still rejected', () => {
        const outcome = requestStatus();
        rejectWith401();
        httpMock.expectOne('/chat/operator/v1/inbox/badges').flush(null, { status: 401, statusText: 'Unauthorized' });
        expect(outcome()).toBe(401);
        expect(logout).not.toHaveBeenCalled();
    });

    it.each([
        { outcome: 'fails', refresh: () => throwError(() => new Error('refresh rejected')) },
        { outcome: 'returns no token', refresh: () => of(null) },
    ])('logs out when the refresh $outcome', ({ refresh }) => {
        refreshResult = refresh();
        const status = requestStatus();
        rejectWith401();
        expect(status()).toBe(401);
        expect(logout).toHaveBeenCalledTimes(1);
    });
});
