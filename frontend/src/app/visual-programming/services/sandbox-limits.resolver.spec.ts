import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, RedirectCommand, Route, Router, RouterStateSnapshot } from '@angular/router';
import { firstValueFrom, Observable, of, throwError } from 'rxjs';

import { routes } from '../../app.routes';
import { ToastService } from '../../services/notifications';
import { GetSandboxLimitsResponse } from '../core/models/sandbox-limits.model';
import { SANDBOX_LIMITS_LOAD_FAILED_MESSAGE, sandboxLimitsResolver } from './sandbox-limits.resolver';
import { SandboxLimitsApiService } from './sandbox-limits-api.service';
import { SandboxLimitsStorageService } from './sandbox-limits-storage.service';

describe('sandboxLimitsResolver', () => {
    let getSandboxLimits: ReturnType<typeof vi.fn>;
    let toast: { error: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        getSandboxLimits = vi.fn();
        toast = { error: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                { provide: SandboxLimitsApiService, useValue: { getSandboxLimits } },
                { provide: ToastService, useValue: toast },
            ],
        });
    });

    function resolve(): Promise<GetSandboxLimitsResponse | RedirectCommand> {
        const result = TestBed.runInInjectionContext(() =>
            sandboxLimitsResolver({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot)
        ) as Observable<GetSandboxLimitsResponse | RedirectCommand>;
        return firstValueFrom(result);
    }

    it('opens the editor with the limits loaded', async () => {
        getSandboxLimits.mockReturnValue(of({ max_execution_timeout_minutes: 45 }));

        const result = await resolve();

        expect(result).toEqual({ max_execution_timeout_minutes: 45 });
        expect(TestBed.inject(SandboxLimitsStorageService).maxExecutionTimeoutMinutes()).toBe(45);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('says why and goes back to the flow list when the limits cannot be loaded', async () => {
        getSandboxLimits.mockReturnValue(throwError(() => new Error('offline')));

        const result = await resolve();

        expect(result).toBeInstanceOf(RedirectCommand);
        const redirect = result as RedirectCommand;
        expect(TestBed.inject(Router).serializeUrl(redirect.redirectTo)).toBe('/flows');
        expect(toast.error).toHaveBeenCalledExactlyOnceWith(SANDBOX_LIMITS_LOAD_FAILED_MESSAGE);
        expect(TestBed.inject(SandboxLimitsStorageService).limits()).toBeNull();
    });

    it('resolves the limits before the flow editor route opens', () => {
        const flatten = (list: Route[]): Route[] => list.flatMap((route) => [route, ...flatten(route.children ?? [])]);
        const editorRoute = flatten(routes).find((route) => route.path === 'flows/:id');

        expect(editorRoute?.resolve?.['sandboxLimits']).toBe(sandboxLimitsResolver);
    });
});
