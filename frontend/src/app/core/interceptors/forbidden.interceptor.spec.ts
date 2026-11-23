import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { GetMeResponse } from '@shared/models';
import { extractErrorCode } from '@shared/utils';
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
                    type: 'client_error',
                    errors: [
                        {
                            code: 'built_in_model_immutable',
                            detail: 'BuiltInModelImmutableError: Built-in models cannot be edited or deleted.',
                            attr: null,
                            context: null,
                        },
                    ],
                },
                { status: 403, statusText: 'Forbidden' }
            );
        }));

    it('does not force a session refresh or toast for a storage_grant_denied 403 (the flow save handler shows it)', () =>
        new Promise<void>((resolve, reject) => {
            httpClient.put('/api/pythonnodes/7/', {}).subscribe({
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

            httpMock.expectOne('/api/pythonnodes/7/').flush(
                {
                    type: 'client_error',
                    errors: [{ code: 'storage_grant_denied', detail: 'Needs Files: Read.', attr: null, context: null }],
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
                    type: 'client_error',
                    errors: [
                        {
                            code: 'in_use_restricted',
                            detail: 'InUseRestrictedError: This flow is in use and cannot be deleted.',
                            attr: null,
                            context: null,
                        },
                    ],
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
                    type: 'client_error',
                    errors: [
                        {
                            code: 'key_value_mode_denied',
                            detail: "You need Key-Value Tables Create and Edit permission to configure a write node on the table 'profiles'.",
                            attr: null,
                            context: null,
                        },
                    ],
                },
                { status: 403, statusText: 'Forbidden' }
            );
        }));

    const TRIGGER_NODES_REFUSAL = {
        type: 'client_error',
        errors: [
            {
                code: 'trigger_nodes_require_use_permission',
                detail: 'Trigger nodes require the Flows Use permission.',
                attr: null,
                context: null,
            },
        ],
    };

    it.each([
        ['flow_with_trigger_nodes_requires_use_permission', 'This flow contains trigger nodes.'],
        ['code_with_secrets_requires_secrets_use_permission', 'This contains code that reads secrets.'],
        ['agent_with_owned_surfaces_requires_surfaces_create_permission', 'This agent owns surfaces.'],
    ])(
        'passes a %s 403 to the caller without a refresh or toast',
        (code, message) =>
            new Promise<void>((resolve, reject) => {
                httpClient.post('/api/graphs/1/copy/', { name: 'Orders' }).subscribe({
                    next: () => reject(new Error('expected the request to error')),
                    error: (err: HttpErrorResponse) => {
                        try {
                            expect(err.status).toBe(403);
                            expect(extractErrorCode(err)).toBe(code);
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
                    .flush(
                        { type: 'client_error', errors: [{ code, detail: message, attr: null, context: null }] },
                        { status: 403, statusText: 'Forbidden' }
                    );
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
                        expect(toastService.error).toHaveBeenCalledWith(
                            'Trigger nodes require the Flows Use permission.'
                        );
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

    it('still forces a session refresh for an unrelated 403 (e.g. stale permissions)', () => {
        const body = {
            type: 'client_error',
            errors: [
                {
                    code: 'permission_denied',
                    detail: 'PermissionDenied: You do not have access to this resource.',
                    attr: null,
                },
            ],
        };
        return new Promise<void>((resolve, reject) => {
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

            httpMock.expectOne('/api/llm-models/1/').flush(body, { status: 403, statusText: 'Forbidden' });
        });
    });

    it('says "Forbidden" for a 403 whose body names no reason', () =>
        new Promise<void>((resolve, reject) => {
            httpClient.get('/api/llm-models/1/').subscribe({
                next: () => reject(new Error('expected the request to error')),
                error: () => {
                    try {
                        expect(toastService.error).toHaveBeenCalledWith('Forbidden');
                        resolve();
                    } catch (e) {
                        reject(e as Error);
                    }
                },
            });

            httpMock.expectOne('/api/llm-models/1/').flush(null, { status: 403, statusText: 'Forbidden' });
        }));
});
