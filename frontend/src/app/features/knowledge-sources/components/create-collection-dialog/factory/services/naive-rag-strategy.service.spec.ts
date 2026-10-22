import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../../../../services/config';
import { NaiveRagChunkStrategy } from '../../../../enums/naive-rag-chunk-strategy';
import { NaiveRagDocumentConfig } from '../../../../models/naive-rag-document.model';
import { NaiveRagDocumentsStorageService } from '../../../../services/naive-rag-documents-storage.service';
import { NaiveRagStrategy } from './naive-rag-strategy.service';

const ESTIMATE_URL = 'http://api/process-rag-indexing/estimate/';

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

describe('NaiveRagStrategy estimateIndexing', () => {
    let strategy: NaiveRagStrategy;
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
        strategy = TestBed.inject(NaiveRagStrategy);
        storage = TestBed.inject(NaiveRagDocumentsStorageService);
        http = TestBed.inject(HttpTestingController);

        strategy.create(5, 1).subscribe();
        http.expectOne('http://api/naive-rag/collections/5/naive-rag/').flush({
            message: 'ok',
            naive_rag: { naive_rag_id: 7, collection_id: 5 },
        });
        storage.fetchDocumentConfigs(7).subscribe();
        http.expectOne('http://api/naive-rag/7/document-configs/').flush({
            naive_rag_id: 7,
            total_configs: 2,
            configs: [buildConfig(1), buildConfig(2)],
        });
    });

    it('sends the unsaved settings of edited documents only', () => {
        storage.setPendingField(1, 'chunk_size', 500);

        strategy.estimateIndexing([1, 2]).subscribe();

        const body = http.expectOne(ESTIMATE_URL).request.body;
        expect(body.document_config_ids).toEqual([1, 2]);
        expect(body.document_configs).toEqual([
            {
                document_config_id: 1,
                chunk_strategy: 'token',
                chunk_size: 500,
                chunk_overlap: 100,
                additional_params: ADDITIONAL_PARAMS,
            },
        ]);
    });

    it('ignores edits of documents that are not being indexed', () => {
        storage.setPendingField(2, 'chunk_size', 500);

        strategy.estimateIndexing([1]).subscribe();

        const body = http.expectOne(ESTIMATE_URL).request.body;
        expect('document_configs' in body).toBe(false);
    });

    it('resolves to null when the server rejects the pending settings', () => {
        storage.setPendingField(1, 'chunk_overlap', 5000);
        let result: unknown = 'unset';

        strategy.estimateIndexing([1]).subscribe((value) => (result = value));
        http.expectOne(ESTIMATE_URL).flush({ detail: 'invalid' }, { status: 400, statusText: 'Bad Request' });

        expect(result).toBeNull();
    });
});
