import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { BinnedSecret } from '@shared/models';

import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';
import { SecretsApiService } from './secrets-api.service';

const BIN = '/api/secrets/recycle-bin/';

function binEntry(id: number) {
    return { id, name: `KEY_${id}`, deleted_at: '2026-10-01T10:00:00Z', days_left: 5 };
}

describe('SecretsApiService binned secrets', () => {
    let service: SecretsApiService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(SecretsApiService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('reads a bin that fits in one page, keeping only the id and name, with no forbidden reload', () => {
        let result: BinnedSecret[] | undefined;
        service.getBinnedSecrets().subscribe((secrets) => (result = secrets));

        const request = httpMock.expectOne(`${BIN}?limit=100&offset=0`);
        expect(request.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
        request.flush({ count: 2, next: null, previous: null, results: [binEntry(1), binEntry(2)] });

        expect(result).toEqual([
            { id: 1, name: 'KEY_1' },
            { id: 2, name: 'KEY_2' },
        ]);
    });

    it('reads every page when the bin holds more than one', () => {
        let result: BinnedSecret[] | undefined;
        service.getBinnedSecrets().subscribe((secrets) => (result = secrets));

        const first = Array.from({ length: 100 }, (_, index) => binEntry(index + 1));
        httpMock
            .expectOne(`${BIN}?limit=100&offset=0`)
            .flush({ count: 101, next: null, previous: null, results: first });
        httpMock
            .expectOne(`${BIN}?limit=100&offset=100`)
            .flush({ count: 101, next: null, previous: null, results: [binEntry(101)] });

        expect(result).toHaveLength(101);
        expect(result?.at(-1)).toEqual({ id: 101, name: 'KEY_101' });
    });

    it('returns an empty list for an empty bin', () => {
        let result: BinnedSecret[] | undefined;
        service.getBinnedSecrets().subscribe((secrets) => (result = secrets));

        httpMock.expectOne(`${BIN}?limit=100&offset=0`).flush({ count: 0, next: null, previous: null, results: [] });

        expect(result).toEqual([]);
    });
});
