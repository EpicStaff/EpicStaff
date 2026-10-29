import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { BulkDeleteResponse } from '@shared/models';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ConfigService } from '../../../services/config';
import { LLMConfigService } from './llm-config.service';

function buildResponse(overrides: Partial<BulkDeleteResponse> = {}): BulkDeleteResponse {
    return {
        dry_run: false,
        deleted_count: 0,
        deleted_ids: [],
        deletable_ids: [],
        not_found_ids: [],
        skipped: [],
        usage: {},
        ...overrides,
    };
}

describe('LLMConfigService', () => {
    let service: LLMConfigService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as ConfigService },
            ],
        });
        service = TestBed.inject(LLMConfigService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('sends dry_run=true in the query and a body of exactly { ids } for a dry run', () => {
        service.bulkDelete([1, 2], { dryRun: true }).subscribe();

        const req = httpMock.expectOne((request) => request.url === '/api/llm-configs/bulk-delete/');
        expect(req.request.method).toBe('POST');
        expect(req.request.params.get('dry_run')).toBe('true');
        expect(req.request.body).toEqual({ ids: [1, 2] });
        req.flush(buildResponse({ dry_run: true, deletable_ids: [1, 2] }));
    });

    it('sends no dry_run param and a body of exactly { ids } for a real delete', () => {
        service.bulkDelete([1, 2]).subscribe();

        const req = httpMock.expectOne((request) => request.url === '/api/llm-configs/bulk-delete/');
        expect(req.request.method).toBe('POST');
        expect(req.request.params.has('dry_run')).toBe(false);
        expect(req.request.body).toEqual({ ids: [1, 2] });
        req.flush(buildResponse({ deleted_ids: [1, 2], deleted_count: 2 }));
    });
});
