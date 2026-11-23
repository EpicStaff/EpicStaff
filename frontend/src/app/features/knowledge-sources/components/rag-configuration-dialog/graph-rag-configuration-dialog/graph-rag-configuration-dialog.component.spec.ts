// Pins where the Graph RAG dialog says why indexing was refused (under the fields or in a toast) at the unit layer:
// the configuration component it drives is replaced with a fake that knows which fields it shows.
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { ApiErrorDetail } from '@shared/models';
import { of, throwError } from 'rxjs';

import { ToastService } from '../../../../../services/notifications';
import { CollectionsStorageService } from '../../../services/collections-storage.service';
import { GraphRagService } from '../../../services/graph-rag.service';
import { GraphRagDocumentsStorageService } from '../../../services/graph-rag-documents-storage.service';
import { IndexingConfirmationDialogService } from '../../../services/indexing-confirmation-dialog.service';
import { KnowledgeSourcesPollingService } from '../../../services/knowledge-sources-polling.service';
import { RagIndexingService } from '../../../services/rag-indexing.service';
import { GraphRagConfigurationDialog } from './graph-rag-configuration-dialog.component';

describe('GraphRagConfigurationDialog indexing refused', () => {
    /** A configuration showing the fields `fields`; it records the errors it was asked to show under them. */
    function fakeConfiguration(fields: string[]) {
        const shownInline: ApiErrorDetail[] = [];
        return {
            shownInline,
            getConfigurationData: () => ({}),
            getIndexingDocuments: () => [{ configId: 7, fileName: 'a.pdf', wasIndexed: false }],
            shouldSaveConfig: () => false,
            getPendingDeleteDocumentIds: () => [],
            hasUnsavedChanges: () => false,
            setServerValidationErrors: (errors: ApiErrorDetail[]) => shownInline.push(...errors),
            showsServerErrorsInline: (errors: ApiErrorDetail[]) =>
                errors.every((error) => error.attr !== null && fields.includes(error.attr)),
        };
    }

    function refusal(attr: string, detail: string): HttpErrorResponse {
        return new HttpErrorResponse({
            status: 400,
            error: { type: 'validation_error', errors: [{ code: 'invalid', detail, attr, context: null }] },
        });
    }

    function runIndexing(configuration: ReturnType<typeof fakeConfiguration>, error: HttpErrorResponse) {
        const toastError = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                { provide: DIALOG_DATA, useValue: { ragId: 3, ragType: 'graph', collectionId: 1 } },
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: ToastService, useValue: { error: toastError, success: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: IndexingConfirmationDialogService, useValue: { confirm: () => of(true) } },
                { provide: RagIndexingService, useValue: { startIndexing: () => throwError(() => error) } },
                { provide: KnowledgeSourcesPollingService, useValue: {} },
                {
                    provide: CollectionsStorageService,
                    useValue: {
                        processingConfigIds: signal(new Set<number>()),
                        getRagStatus: () => 'new',
                        getRagModelNames: () => ({ embedderName: null, llmName: null }),
                    },
                },
                { provide: GraphRagService, useValue: {} },
                { provide: GraphRagDocumentsStorageService, useValue: { documents: signal([]) } },
            ],
        });
        const dialog = TestBed.runInInjectionContext(() => new GraphRagConfigurationDialog());
        Reflect.set(dialog, 'ragConfiguration', () => configuration);

        dialog.runIndexing();

        return { toastError };
    }

    it('says in a toast why indexing was refused when the error names a field the configuration does not show', () => {
        const configuration = fakeConfiguration(['chunk_size']);

        const { toastError } = runIndexing(configuration, refusal('document_ids', 'Unknown document.'));

        expect(toastError).toHaveBeenCalledWith('document_ids: Unknown document.');
        expect(configuration.shownInline).toEqual([]);
    });

    it('shows the error under its field, and no toast, when the configuration shows that field', () => {
        const configuration = fakeConfiguration(['chunk_size']);

        const { toastError } = runIndexing(configuration, refusal('chunk_size', 'Too small.'));

        expect(configuration.shownInline.map((error) => error.detail)).toEqual(['Too small.']);
        expect(toastError).not.toHaveBeenCalled();
    });
});
