import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { IndexingEstimate, StartIndexingDtoRequest } from '../models/base-rag.model';
import { RagIndexingService } from './rag-indexing.service';

const REQUEST: StartIndexingDtoRequest = { rag_id: 1, rag_type: 'naive', document_config_ids: [1] };
const ESTIMATE: IndexingEstimate = {
    rag_type: 'naive',
    document_count: 1,
    chunk_count: 2,
    embedding: { tokens: 10, exact: true, cost_usd: 0.1 },
    llm: null,
};
const ESTIMATE_URL = 'http://api/process-rag-indexing/estimate/';

describe('RagIndexingService estimate', () => {
    let service: RagIndexingService;
    let http: HttpTestingController;

    beforeEach(() => {
        vi.useFakeTimers();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: 'http://api/' } },
            ],
        });
        service = TestBed.inject(RagIndexingService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('emits the estimate on success', () => {
        let result: IndexingEstimate | null | undefined;
        service.estimateIndexingOrNull(REQUEST).subscribe((value) => (result = value));
        http.expectOne(ESTIMATE_URL).flush(ESTIMATE);
        expect(result).toEqual(ESTIMATE);
    });

    it('resolves to null on an http error', () => {
        let result: IndexingEstimate | null | undefined;
        service.estimateIndexingOrNull(REQUEST).subscribe((value) => (result = value));
        http.expectOne(ESTIMATE_URL).flush('boom', { status: 500, statusText: 'Server Error' });
        expect(result).toBeNull();
    });

    it('resolves to null when the request exceeds the timeout', () => {
        let result: IndexingEstimate | null | undefined;
        service.estimateIndexingOrNull(REQUEST).subscribe((value) => (result = value));
        http.expectOne(ESTIMATE_URL);
        vi.advanceTimersByTime(3001);
        expect(result).toBeNull();
    });

    it('estimateIndexing propagates errors', () => {
        let error: unknown;
        service.estimateIndexing(REQUEST).subscribe({ error: (err: unknown) => (error = err) });
        http.expectOne(ESTIMATE_URL).flush('boom', { status: 500, statusText: 'Server Error' });
        expect(error).toBeInstanceOf(HttpErrorResponse);
    });
});
