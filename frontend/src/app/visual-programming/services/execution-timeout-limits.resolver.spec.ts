import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, RedirectCommand, Route, Router, RouterStateSnapshot } from '@angular/router';
import { firstValueFrom, Observable, of, throwError } from 'rxjs';

import { routes } from '../../app.routes';
import { ToastService } from '../../services/notifications';
import { ExecutionTimeoutLimits } from '../core/models/execution-timeout-limits.model';
import { executionTimeoutLimitsResolver } from './execution-timeout-limits.resolver';
import { ExecutionTimeoutLimitsApiService } from './execution-timeout-limits-api.service';
import { ExecutionTimeoutLimitsStorageService } from './execution-timeout-limits-storage.service';

describe('executionTimeoutLimitsResolver', () => {
    let getExecutionTimeoutLimits: ReturnType<typeof vi.fn>;
    let toast: { error: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        getExecutionTimeoutLimits = vi.fn();
        toast = { error: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                { provide: ExecutionTimeoutLimitsApiService, useValue: { getExecutionTimeoutLimits } },
                { provide: ToastService, useValue: toast },
            ],
        });
    });

    function resolve(): Promise<ExecutionTimeoutLimits | RedirectCommand> {
        const result = TestBed.runInInjectionContext(() =>
            executionTimeoutLimitsResolver({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot)
        ) as Observable<ExecutionTimeoutLimits | RedirectCommand>;
        return firstValueFrom(result);
    }

    it('opens the editor with the limits loaded', async () => {
        getExecutionTimeoutLimits.mockReturnValue(of({ min_seconds: 5, default_seconds: 120, max_seconds: 3600 }));

        const result = await resolve();

        const limits: ExecutionTimeoutLimits = { minSeconds: 5, defaultSeconds: 120, maxSeconds: 3600 };
        expect(result).toEqual(limits);
        expect(TestBed.inject(ExecutionTimeoutLimitsStorageService).limits()).toEqual(limits);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('says why and goes back to the flow list when the limits cannot be loaded', async () => {
        getExecutionTimeoutLimits.mockReturnValue(throwError(() => new Error('offline')));

        const result = await resolve();

        expect(result).toBeInstanceOf(RedirectCommand);
        expect(TestBed.inject(Router).serializeUrl((result as RedirectCommand).redirectTo)).toBe('/flows');
        expect(toast.error).toHaveBeenCalledExactlyOnceWith(
            'Could not load the execution timeout limits, so the flow cannot be opened.'
        );
        expect(() => TestBed.inject(ExecutionTimeoutLimitsStorageService).limits()).toThrow(/not loaded/);
    });

    it('resolves the limits before the flow editor route opens', () => {
        const flatten = (list: Route[]): Route[] => list.flatMap((route) => [route, ...flatten(route.children ?? [])]);
        const editorRoute = flatten(routes).find((route) => route.path === 'flows/:id');

        expect(editorRoute?.resolve?.['executionTimeoutLimits']).toBe(executionTimeoutLimitsResolver);
    });
});
