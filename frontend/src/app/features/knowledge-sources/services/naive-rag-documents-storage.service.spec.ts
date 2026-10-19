import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { NaiveRagChunkStrategy } from '../enums/naive-rag-chunk-strategy';
import { NaiveRagDocumentConfig } from '../models/naive-rag-document.model';
import { NaiveRagDocumentsStorageService } from './naive-rag-documents-storage.service';

const ADDITIONAL_PARAMS: NaiveRagDocumentConfig['additional_params'] = {
    markdown: {},
    character: {},
    csv: {},
    html: {},
    token: {},
    json: {},
};

function buildConfig(id: number): NaiveRagDocumentConfig {
    return {
        naive_rag_document_id: id,
        document_id: id,
        file_name: `file-${id}.txt`,
        chunk_strategy: NaiveRagChunkStrategy.TOKEN,
        chunk_size: 1000,
        chunk_overlap: 100,
        additional_params: ADDITIONAL_PARAMS,
        status: 'completed',
        outdated_reasons: null,
        error_message: null,
        failed_at: null,
        total_chunks: 1,
        total_embeddings: 1,
        created_at: '',
        processed_at: null,
    };
}

describe('NaiveRagDocumentsStorageService bulkPartialUpdate', () => {
    let storage: NaiveRagDocumentsStorageService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: 'http://api/' } },
            ],
        });
        storage = TestBed.inject(NaiveRagDocumentsStorageService);
        http = TestBed.inject(HttpTestingController);

        storage.fetchDocumentConfigs(7).subscribe();
        http.expectOne('http://api/naive-rag/7/document-configs/').flush({
            naive_rag_id: 7,
            total_configs: 2,
            configs: [buildConfig(1), buildConfig(2)],
        });
    });

    it('sends the full effective settings of edited documents only', () => {
        storage.setPendingField(1, 'chunk_size', 500);

        storage.bulkPartialUpdate(7, [1, 2]).subscribe();

        const request = http.expectOne('http://api/naive-rag/7/document-configs/bulk-update/');
        expect(request.request.method).toBe('PUT');
        expect(request.request.body).toEqual([
            {
                id: 1,
                chunk_strategy: 'token',
                chunk_size: 500,
                chunk_overlap: 100,
                additional_params: ADDITIONAL_PARAMS,
            },
        ]);
    });
});
