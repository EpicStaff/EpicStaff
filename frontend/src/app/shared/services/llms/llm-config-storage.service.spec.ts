import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { LlmConfigTimeoutLimits } from '@shared/models';
import { firstValueFrom } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { AppStorageService } from '../app-storage.service';
import { provideSharedStorages } from '../shared-storages.providers';
import { LlmConfigStorageService } from './llm-config-storage.service';

const LIMITS_URL = '/api/llm-config-timeout-limits/';
const LIMITS: LlmConfigTimeoutLimits = { min_seconds: 1, max_seconds: 3600 };

describe('LlmConfigStorageService timeout limits', () => {
    let storage: LlmConfigStorageService;
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
        storage = TestBed.inject(LlmConfigStorageService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => http.verify());

    async function loadWith(limits: LlmConfigTimeoutLimits): Promise<LlmConfigTimeoutLimits> {
        const loaded = firstValueFrom(storage.getTimeoutLimits());
        http.expectOne(LIMITS_URL).flush(limits);
        return loaded;
    }

    it('gives the limits the backend returned', async () => {
        expect(await loadWith(LIMITS)).toEqual(LIMITS);
    });

    it('asks the backend once when a second caller asks before the first response', async () => {
        const first = firstValueFrom(storage.getTimeoutLimits());
        const second = firstValueFrom(storage.getTimeoutLimits());

        http.expectOne(LIMITS_URL).flush(LIMITS);

        expect(await first).toEqual(LIMITS);
        expect(await second).toEqual(LIMITS);
    });

    it('asks the backend once per session', async () => {
        await loadWith(LIMITS);

        const again = await firstValueFrom(storage.getTimeoutLimits());

        http.expectNone(LIMITS_URL);
        expect(again).toEqual(LIMITS);
    });

    it('asks the backend again after a failed request', async () => {
        const failed = firstValueFrom(storage.getTimeoutLimits());
        http.expectOne(LIMITS_URL).flush(null, { status: 500, statusText: 'Server Error' });
        await expect(failed).rejects.toBeDefined();

        expect(await loadWith(LIMITS)).toEqual(LIMITS);
    });

    it('forgets the limits on logout, so the next session asks the backend again', async () => {
        await loadWith(LIMITS);

        TestBed.inject(AppStorageService).clearAll();

        expect(await loadWith({ min_seconds: 5, max_seconds: 600 })).toEqual({ min_seconds: 5, max_seconds: 600 });
    });
});
