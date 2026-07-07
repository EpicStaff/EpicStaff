import { ChangeDetectionStrategy, Component, computed, inject, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
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

    processingDocIds = computed(() => {
        const processing = this.collectionsStorage.processingConfigIds();
        return this.documentsStorage
            .documents()
            .map((d) => d.naive_rag_document_id)
            .filter((id) => processing.has(id));
    });

    isIndexing = computed(() => this.processingDocIds().length > 0);

    onClose(): void {
        this.dialogRef.close();
    }

    runIndexing(): void {
        const { configIds, fileNames } = this.ragConfiguration().getDocumentsForIndexing();
        if (!fileNames.length) return;

        const indexingDocs = this.ragConfiguration().getIndexingDocuments();

        this.confirmation
            .confirm(getIndexingConfirmationData(indexingDocs))
            .pipe(
                filter((result) => result === true),
                switchMap(() =>
                    this.ragIndexingService.startIndexing({
                        rag_id: this.data.ragId,
                        rag_type: 'naive',
                        document_config_ids: configIds,
                    })
                ),
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
