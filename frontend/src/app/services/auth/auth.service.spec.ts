// Side-effect import: AuthService's dependency graph reads the `validationErrors` augmentation this module declares
// (see forbidden.interceptor.spec.ts), so without it the spec program fails to type-check.
import '../../core/interceptors/validation-errors.interceptor';

import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { APP_STORAGE } from '@shared/services';

import { authInterceptor } from '../../core/interceptors/auth.interceptor';
import { AppReturnUrlService } from '../../features/plugins/services/app-return-url.service';
import { ConfigService } from '../config';
import { AuthService } from './auth.service';
import { PermissionsService } from './permissions.service';
import { ProfileService } from './profile.service';

describe('AuthService sign-out', () => {
    let authService: AuthService;
    let httpMock: HttpTestingController;
    let returnUrl: AppReturnUrlService;
    let clearCurrentUser: ReturnType<typeof vi.fn>;
    let navigate: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
        clearCurrentUser = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([authInterceptor])),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: ProfileService, useValue: { clearCurrentUser } as unknown as ProfileService },
                { provide: PermissionsService, useValue: { resolveDefaultRoute: () => '/agents' } },
                // One storage stands for all of them: the way back from an app, kept in sessionStorage.
                { provide: APP_STORAGE, useExisting: AppReturnUrlService, multi: true },
            ],
        });
        authService = TestBed.inject(AuthService);
        httpMock = TestBed.inject(HttpTestingController);
        returnUrl = TestBed.inject(AppReturnUrlService);
        navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

        authService.storeAccessToken('access-token');
        returnUrl.record('/flows/my');
    });

    afterEach(() => {
        httpMock.verify();
        sessionStorage.clear();
    });

    it('forgets the session when a failed token refresh signs the user out, as a requested sign-out does', () => {
        TestBed.inject(HttpClient)
            .get('/api/flows/')
            .subscribe({ error: () => undefined });
        httpMock.expectOne('/api/flows/').flush(null, { status: 401, statusText: 'Unauthorized' });
        httpMock.expectOne('/api/auth/refresh/').flush(null, { status: 401, statusText: 'Unauthorized' });

        expect(authService.getAccessToken()).toBeNull();
        expect(clearCurrentUser).toHaveBeenCalled();
        expect(returnUrl.url()).toBe('/agents');
        expect(sessionStorage.getItem('epicstaff.appReturnUrl')).toBeNull();
        expect(navigate).toHaveBeenCalledWith(['/login']);
    });

    it('forgets the session at once on a requested sign-out, before the server answers', () => {
        authService.logout().subscribe();

        expect(clearCurrentUser).toHaveBeenCalled();
        expect(returnUrl.url()).toBe('/agents');
        expect(navigate).not.toHaveBeenCalled();

        httpMock.expectOne('/api/auth/logout/').flush(null);

        expect(authService.getAccessToken()).toBeNull();
        expect(navigate).toHaveBeenCalledWith(['/login']);
    });
});
