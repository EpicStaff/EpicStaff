// Side-effect import: this module's `declare module '@angular/common/http'` augmentation
// (adding `validationErrors` to HttpErrorResponse) only applies to files TypeScript actually
// compiles together. ProfileService's dependency graph pulls in shared/utils/http-error.util.ts,
// which reads that property, so without this import the whole spec program fails to type-check.
import './validation-errors.interceptor';

import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { GetMeResponse } from '@shared/models';
import { of } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { forbiddenInterceptor } from './forbidden.interceptor';

describe('forbiddenInterceptor', () => {
    let httpClient: HttpClient;
    let httpMock: HttpTestingController;
    let profileService: { clearCurrentUser: ReturnType<typeof vi.fn>; bootstrapUser: ReturnType<typeof vi.fn> };
    let toastService: { error: ReturnType<typeof vi.fn> };
    let router: { navigateByUrl: ReturnType<typeof vi.fn>; url: string };

    beforeEach(() => {
        profileService = { clearCurrentUser: vi.fn(), bootstrapUser: vi.fn() };
        toastService = { error: vi.fn() };
        router = { navigateByUrl: vi.fn(), url: '/current-page' };

        profileService.bootstrapUser.mockReturnValue(of({} as GetMeResponse));
        router.navigateByUrl.mockResolvedValue(true);

        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([forbiddenInterceptor])),
                provideHttpClientTesting(),
                { provide: ProfileService, useValue: profileService as unknown as ProfileService },
                { provide: ToastService, useValue: toastService as unknown as ToastService },
                { provide: Router, useValue: router as unknown as Router },
            ],
        });

        httpClient = TestBed.inject(HttpClient);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('does not force a session refresh or toast for a built_in_model_immutable 403', () =>
        new Promise<void>((resolve, reject) => {
            httpClient.get('/api/llm-models/1/').subscribe({
                next: () => reject(new Error('expected the request to error')),
                error: (err: HttpErrorResponse) => {
                    try {
                        expect(err.status).toBe(403);
                        expect(profileService.clearCurrentUser).not.toHaveBeenCalled();
                        expect(router.navigateByUrl).not.toHaveBeenCalled();
                        expect(toastService.error).not.toHaveBeenCalled();
                        resolve();
                    } catch (e) {
                        reject(e as Error);
                    }
                },
            });

            const req = httpMock.expectOne('/api/llm-models/1/');
            req.flush(
                {
                    status_code: 403,
                    code: 'built_in_model_immutable',
                    message: 'BuiltInModelImmutableError: Built-in models cannot be edited or deleted.',
                },
                { status: 403, statusText: 'Forbidden' }
            );
        }));

    it('still forces a session refresh for an unrelated 403 (e.g. stale permissions)', () =>
        new Promise<void>((resolve, reject) => {
            httpClient.get('/api/llm-models/1/').subscribe({
                next: () => reject(new Error('expected the request to error')),
                error: (err: HttpErrorResponse) => {
                    try {
                        expect(err.status).toBe(403);
                        expect(profileService.clearCurrentUser).toHaveBeenCalled();
                        expect(toastService.error).toHaveBeenCalledWith(
                            'PermissionDenied: You do not have access to this resource.'
                        );
                        resolve();
                    } catch (e) {
                        reject(e as Error);
                    }
                },
            });

            const req = httpMock.expectOne('/api/llm-models/1/');
            req.flush(
                {
                    status_code: 403,
                    code: 'permission_denied',
                    message: 'PermissionDenied: You do not have access to this resource.',
                },
                { status: 403, statusText: 'Forbidden' }
            );
        }));
});
