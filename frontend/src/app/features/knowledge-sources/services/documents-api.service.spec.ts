import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { DocumentDetail, ImportFromStorageResponse } from '../models/document.model';
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

describe('DocumentsApiService document content', () => {
    let service: DocumentsApiService;
    let httpMock: HttpTestingController;

    const detail: DocumentDetail = {
        document_id: 5,
        file_name: 'notes.txt',
        file_size: 8,
        file_type: 'txt',
        source_collection: 2,
        collection_name: 'Docs',
        content_hash: 'a'.repeat(64),
        shared_with_collections: [{ collection_id: 3, collection_name: 'Copies' }],
    };

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

    it('GETs the document text for editing', () => {
        service.getDocumentText(5).subscribe();

        const request = httpMock.expectOne('http://api.test/api/documents/5/content/');
        expect(request.request.method).toBe('GET');
        request.flush({ ...detail, text: 'old text' });
    });

    it('PUTs the new text as a multipart file with the scope and the expected hash', async () => {
        service.updateDocumentContent(5, 'notes.txt', 'new text', 'all_collections', 'b'.repeat(64)).subscribe();

        const request = httpMock.expectOne('http://api.test/api/documents/5/content/');
        expect(request.request.method).toBe('PUT');
        const body = request.request.body as FormData;
        const file = body.get('file') as File;
        expect(file.name).toBe('notes.txt');
        expect(await file.text()).toBe('new text');
        expect(body.get('scope')).toBe('all_collections');
        expect(body.get('content_hash')).toBe('b'.repeat(64));
        request.flush(detail);
    });
});
