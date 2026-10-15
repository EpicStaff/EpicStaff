import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { computed } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AppStorageService } from '@shared/services';
import { firstValueFrom } from 'rxjs';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { ConfigService } from '../../services/config';
import { GetExecutionTimeoutLimitsResponse } from '../core/models/execution-timeout-limits.model';
import { provideVisualProgrammingStorages } from '../visual-programming.providers';
import { ExecutionTimeoutLimitsStorageService } from './execution-timeout-limits-storage.service';

const LIMITS_URL = '/api/execution-timeout-limits/';
const RESPONSE: GetExecutionTimeoutLimitsResponse = { min_seconds: 5, default_seconds: 120, max_seconds: 3600 };

describe('ExecutionTimeoutLimitsStorageService', () => {
    let storage: ExecutionTimeoutLimitsStorageService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                ...provideVisualProgrammingStorages(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                // The other storage registered beside this one needs it; it plays no part here.
                { provide: ActiveOrgService, useValue: {} },
            ],
        });
        storage = TestBed.inject(ExecutionTimeoutLimitsStorageService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => http.verify());

    async function loadWith(response: GetExecutionTimeoutLimitsResponse): Promise<void> {
        const loaded = firstValueFrom(storage.load());
        http.expectOne(LIMITS_URL).flush(response);
        await loaded;
    }

    it('refuses to give the limits before they are loaded', () => {
        expect(() => storage.limits()).toThrow(/not loaded/);
    });

    it('gives the limits the backend returned, in seconds', async () => {
        await loadWith(RESPONSE);

        expect(storage.limits()).toEqual({ minSeconds: 5, defaultSeconds: 120, maxSeconds: 3600 });
    });

    it('keeps a missing maximum as none', async () => {
        await loadWith({ ...RESPONSE, max_seconds: null });

        expect(storage.limits().maxSeconds).toBeNull();
    });

    it('asks the backend once per session', async () => {
        await loadWith(RESPONSE);

        const again = await firstValueFrom(storage.load());

        http.expectNone(LIMITS_URL);
        expect(again).toEqual(storage.limits());
    });

    it('forgets the limits on logout, so the next session asks the backend again', async () => {
        await loadWith(RESPONSE);

        TestBed.inject(AppStorageService).clearAll();

        expect(() => storage.limits()).toThrow(/not loaded/);
        await loadWith({ ...RESPONSE, max_seconds: 600 });
        expect(storage.limits().maxSeconds).toBe(600);
    });

    it('never makes a reactive reader depend on the limits, so clearing them re-runs nothing', async () => {
        await loadWith(RESPONSE);
        let runs = 0;
        const maximum = computed(() => {
            runs++;
            return storage.limits().maxSeconds;
        });
        expect(maximum()).toBe(3600);

        storage.clear();

        expect(maximum()).toBe(3600);
        expect(runs).toBe(1);
    });
});
