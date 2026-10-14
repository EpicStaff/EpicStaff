import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { computed } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AppStorageService } from '@shared/services';
import { firstValueFrom } from 'rxjs';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { ConfigService } from '../../services/config';
import { provideVisualProgrammingStorages } from '../visual-programming.providers';
import { SandboxLimitsStorageService } from './sandbox-limits-storage.service';

const LIMITS_URL = '/api/sandbox-limits/';

describe('SandboxLimitsStorageService', () => {
    let storage: SandboxLimitsStorageService;
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
        storage = TestBed.inject(SandboxLimitsStorageService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => http.verify());

    async function loadWith(maxMinutes: number): Promise<void> {
        const loaded = firstValueFrom(storage.load());
        http.expectOne(LIMITS_URL).flush({ max_execution_timeout_minutes: maxMinutes });
        await loaded;
    }

    it('refuses to give a ceiling before the limits are loaded', () => {
        expect(storage.limits()).toBeNull();
        expect(() => storage.maxExecutionTimeoutMinutes()).toThrow(/not loaded/);
    });

    it('gives the ceiling the backend returned', async () => {
        await loadWith(45);

        expect(storage.maxExecutionTimeoutMinutes()).toBe(45);
    });

    it('asks the backend once per session', async () => {
        await loadWith(45);

        const again = await firstValueFrom(storage.load());

        http.expectNone(LIMITS_URL);
        expect(again).toEqual({ max_execution_timeout_minutes: 45 });
    });

    it('takes limits set directly', () => {
        storage.setLimits({ max_execution_timeout_minutes: 10 });

        expect(storage.maxExecutionTimeoutMinutes()).toBe(10);
    });

    it('forgets the limits on logout, so the next session asks the backend again', async () => {
        await loadWith(45);

        TestBed.inject(AppStorageService).clearAll();

        expect(storage.limits()).toBeNull();
        expect(() => storage.maxExecutionTimeoutMinutes()).toThrow();
        await loadWith(30);
        expect(storage.maxExecutionTimeoutMinutes()).toBe(30);
    });

    it('never makes a reactive reader of the ceiling depend on the limits, so clearing them re-runs nothing', () => {
        storage.setLimits({ max_execution_timeout_minutes: 45 });
        let runs = 0;
        const ceiling = computed(() => {
            runs++;
            return storage.maxExecutionTimeoutMinutes();
        });
        expect(ceiling()).toBe(45);

        storage.clear();
        storage.setLimits({ max_execution_timeout_minutes: 30 });

        expect(ceiling()).toBe(45);
        expect(runs).toBe(1);
    });

    it('still lets a reader follow the limits through the limits signal', () => {
        const ceiling = computed(() => storage.limits()?.max_execution_timeout_minutes ?? null);
        storage.setLimits({ max_execution_timeout_minutes: 45 });
        expect(ceiling()).toBe(45);

        storage.clear();

        expect(ceiling()).toBeNull();
    });
});
