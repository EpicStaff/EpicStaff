import { ChangeDetectionStrategy, Component, computed, inject, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { EMPTY, Observable, of } from 'rxjs';
import { filter, switchMap } from 'rxjs/operators';

import { getIndexingConfirmationData } from '../../../helpers/get-indexing-confirmation-data.util';
import { CollectionsStorageService } from '../../../services/collections-storage.service';
import { NaiveRagDocumentsStorageService } from '../../../services/naive-rag-documents-storage.service';
import { NaiveRagConfigurationComponent } from '../../naive-rag-configuration/naive-rag-configuration.component';
import { RagConfigurationDialogComponent } from '../rag-configuration-dialog.component';

@Component({
    selector: 'app-naive-rag-configuration-dialog',
    templateUrl: './naive-rag-configuration-dialog.component.html',
    styleUrls: ['../rag-configuration-dialog.component.scss'],
    imports: [NaiveRagConfigurationComponent, ButtonComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NaiveRagConfigurationDialog extends RagConfigurationDialogComponent {
    private collectionsStorage = inject(CollectionsStorageService);
    private documentsStorage = inject(NaiveRagDocumentsStorageService);
    private ragConfiguration = viewChild.required(NaiveRagConfigurationComponent);
    hasUnsavedChanges = computed(() => this.ragConfiguration().hasUnsavedChanges());
    indexingDisabled = computed(() => !this.ragConfiguration().filteredAndCheckedDocIds().length);

    processingDocIds = computed(() => {
        const processing = this.collectionsStorage.processingConfigIds();
        return this.documentsStorage
            .documents()
            .map((d) => d.naive_rag_document_id)
            .filter((id) => processing.has(id));
    });

    isIndexing = computed(() => this.processingDocIds().length > 0);

    onClose(): void {
        if (!this.hasUnsavedChanges()) {
            this.dialogRef.close();
            return;
        }

        this.confirmation
            .confirm({
                title: 'Unsaved Changes',
                message: 'You have unsaved changes in your Naive RAG Configuration. Would you like to leave?',
                type: 'warning',
                cancelText: 'Cancel',
                confirmText: 'Leave',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) this.dialogRef.close();
            });
    }

    runIndexing(): void {
        const config = this.ragConfiguration();
        const indexingDocs = config.getIndexingDocuments();
        const configIds = indexingDocs.map((d) => d.configId);
        const hasPendingDeletes = config.getPendingDeleteDocumentIds().length > 0;
        if (!configIds.length && !hasPendingDeletes) return;

        const delete$: Observable<unknown> = hasPendingDeletes ? config.bulkDeletePending() : of(null);

        this.confirmation
            .confirm(getIndexingConfirmationData(indexingDocs))
            .pipe(
                filter((result) => result === true),
                switchMap(() => delete$),
                switchMap(() => config.uploadPendingForChecked()),
                switchMap(() => {
                    if (config.hasFailedSavesForChecked()) {
                        this.toast.error('Some documents failed to save. Fix the errors and retry.');
                        return EMPTY;
                    }
                    if (!configIds.length) {
                        this.toast.success('Changes saved');
                        return EMPTY;
                    }
                    return this.ragIndexingService.startIndexing({
                        rag_id: this.data.ragId,
                        rag_type: 'naive',
                        document_config_ids: configIds,
                    });
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success('Indexing started');
                    this.collectionsStorage.markConfigsAsProcessing(configIds);
                    this.collectionsStorage.markRagAsProcessing(this.data.ragId);
                },
                error: () => {
                    this.toast.error('Files re-indexing failed');
                    // If bulkDeletePending() was the stage that failed, its documents are
                    // still optimistically hidden from the table with nothing left to
                    // retry the delete. Recover the same way the "Re-include Files"
                    // button does, rather than leaving them invisible indefinitely.
                    if (hasPendingDeletes) config.initDocuments();
                },
            });
    }
}
