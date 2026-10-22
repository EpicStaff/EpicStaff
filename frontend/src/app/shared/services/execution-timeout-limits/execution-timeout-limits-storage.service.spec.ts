import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { computed } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GetExecutionTimeoutLimitsResponse } from '@shared/models';
import { firstValueFrom } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { AppStorageService } from '../app-storage.service';
import { provideSharedStorages } from '../shared-storages.providers';
import { executionTimeoutLimitsResponse, TEST_EXECUTION_TIMEOUT_LIMITS } from './execution-timeout-limits.testing';
import { ExecutionTimeoutLimitsStorageService } from './execution-timeout-limits-storage.service';

const LIMITS_URL = '/api/execution-timeout-limits/';
const RESPONSE = executionTimeoutLimitsResponse();

describe('ExecutionTimeoutLimitsStorageService', () => {
    let storage: ExecutionTimeoutLimitsStorageService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                ...provideSharedStorages(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
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

        expect(storage.limits()).toEqual(TEST_EXECUTION_TIMEOUT_LIMITS);
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

    it('asks the backend once when a second caller loads before the first response', async () => {
        const first = firstValueFrom(storage.load());
        const second = firstValueFrom(storage.load());

        http.expectOne(LIMITS_URL).flush(RESPONSE);

        expect(await first).toEqual(TEST_EXECUTION_TIMEOUT_LIMITS);
        expect(await second).toEqual(TEST_EXECUTION_TIMEOUT_LIMITS);
    });

    it('asks the backend again after a failed request', async () => {
        const failed = firstValueFrom(storage.load());
        http.expectOne(LIMITS_URL).flush(null, { status: 500, statusText: 'Server Error' });
        await expect(failed).rejects.toBeDefined();

        await loadWith(RESPONSE);

        expect(storage.limits()).toEqual(TEST_EXECUTION_TIMEOUT_LIMITS);
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
