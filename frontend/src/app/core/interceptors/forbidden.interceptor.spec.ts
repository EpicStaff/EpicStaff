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

    it('does not force a session refresh or toast for an in_use_restricted 403 (bulk-delete single-item block)', () =>
        new Promise<void>((resolve, reject) => {
            httpClient.delete('/api/flows/1/').subscribe({
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

            const req = httpMock.expectOne('/api/flows/1/');
            req.flush(
                {
                    status_code: 403,
                    code: 'in_use_restricted',
                    message: 'InUseRestrictedError: This flow is in use and cannot be deleted.',
                },
                { status: 403, statusText: 'Forbidden' }
            );
        }));

    it('does not force a session refresh or toast for a key_value_mode_denied 403', () =>
        new Promise<void>((resolve, reject) => {
            httpClient.post('/api/graphs/1/save-flow/', {}).subscribe({
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

            const req = httpMock.expectOne('/api/graphs/1/save-flow/');
            req.flush(
                {
                    status_code: 403,
                    code: 'key_value_mode_denied',
                    message:
                        "You need Key-Value Tables Create and Edit permission to configure a write node on the table 'profiles'.",
                },
                { status: 403, statusText: 'Forbidden' }
            );
        }));

    const TRIGGER_NODES_REFUSAL = {
        status_code: 403,
        code: 'trigger_nodes_require_use_permission',
        message: 'Trigger nodes require the Flows Use permission.',
    };

    it.each([
        ['flow_with_trigger_nodes_requires_use_permission', 'This flow contains trigger nodes.'],
        ['code_with_secrets_requires_secrets_use_permission', 'This contains code that reads secrets.'],
    ])(
        'passes a %s 403 to the caller without a refresh or toast',
        (code, message) =>
            new Promise<void>((resolve, reject) => {
                httpClient.post('/api/graphs/1/copy/', { name: 'Orders' }).subscribe({
                    next: () => reject(new Error('expected the request to error')),
                    error: (err: HttpErrorResponse) => {
                        try {
                            expect(err.status).toBe(403);
                            expect(err.error.code).toBe(code);
                            expect(profileService.clearCurrentUser).not.toHaveBeenCalled();
                            expect(profileService.bootstrapUser).not.toHaveBeenCalled();
                            expect(router.navigateByUrl).not.toHaveBeenCalled();
                            expect(toastService.error).not.toHaveBeenCalled();
                            resolve();
                        } catch (e) {
                            reject(e as Error);
                        }
                    },
                });

                httpMock
                    .expectOne('/api/graphs/1/copy/')
                    .flush({ status_code: 403, code, message }, { status: 403, statusText: 'Forbidden' });
            })
    );

    it('refreshes permissions on a trigger_nodes_require_use_permission 403 (Use may just have been revoked)', () =>
        new Promise<void>((resolve, reject) => {
            httpClient.post('/api/graphs/1/save/', {}).subscribe({
                next: () => reject(new Error('expected the request to error')),
                error: (err: HttpErrorResponse) => {
                    try {
                        expect(err.status).toBe(403);
                        expect(profileService.clearCurrentUser).toHaveBeenCalled();
                        expect(profileService.bootstrapUser).toHaveBeenCalled();
                        expect(toastService.error).toHaveBeenCalledWith(TRIGGER_NODES_REFUSAL.message);
                        resolve();
                    } catch (e) {
                        reject(e as Error);
                    }
                },
            });

            httpMock
                .expectOne('/api/graphs/1/save/')
                .flush(TRIGGER_NODES_REFUSAL, { status: 403, statusText: 'Forbidden' });
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
