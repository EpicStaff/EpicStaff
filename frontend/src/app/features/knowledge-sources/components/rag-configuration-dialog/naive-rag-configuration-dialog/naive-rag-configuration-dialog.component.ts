import { ChangeDetectionStrategy, Component, computed, inject, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { EMPTY } from 'rxjs';
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
    indexingDisabled = computed(() => !this.ragConfiguration().filteredAndCheckedDocIds().length);
    hasUnsavedChanges = computed(() => this.ragConfiguration().hasUnsavedChanges());

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
        const { configIds, fileNames } = config.getDocumentsForIndexing();
        if (!fileNames.length) return;

        const indexingDocs = config.getIndexingDocuments();

        this.confirmation
            .confirm(getIndexingConfirmationData(indexingDocs))
            .pipe(
                filter((result) => result === true),
                switchMap(() => config.uploadPendingForChecked()),
                switchMap(() => {
                    if (config.hasFailedSavesForChecked()) {
                        this.toast.error('Some documents failed to save. Fix the errors and retry.');
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
                },
                error: () => this.toast.error('Files re-indexing failed'),
            });
    }
}
