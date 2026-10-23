import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { ImportFromStorageResponse } from '../models/document.model';
import { DocumentsApiService } from './documents-api.service';

describe('DocumentsApiService.importFromStorage', () => {
    let service: DocumentsApiService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: 'http://api.test/api/' } },
            ],
        });
        service = TestBed.inject(DocumentsApiService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('POSTs the storage ids, exactly as given, to the collection from-storage endpoint', () => {
        const response: ImportFromStorageResponse = {
            message: 'ok',
            documents: [],
            skipped: [{ storage_file_id: 9, path: 'docs/run.exe', reason: 'unsupported_type' }],
        };
        let received: ImportFromStorageResponse | undefined;

        service.importFromStorage(42, [3, 7, 9]).subscribe((body) => (received = body));

        const request = httpMock.expectOne('http://api.test/api/documents/source-collection/42/from-storage/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ storage_file_ids: [3, 7, 9] });
        request.flush(response, { status: 201, statusText: 'Created' });

        expect(received).toEqual(response);
    });
});
