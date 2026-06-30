import { ChangeDetectionStrategy, Component, computed, inject, viewChild } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { filter, switchMap, take } from 'rxjs/operators';

import { getIndexingConfirmationData } from '../../../helpers/get-indexing-confirmation-data.util';
import { NaiveRagService } from '../../../services/naive-rag.service';
import { NaiveRagDocumentsStorageService } from '../../../services/naive-rag-documents-storage.service';
import { NaiveRagPollingService } from '../../../services/naive-rag-polling.service';
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
    private naiveRagService = inject(NaiveRagService);
    private documentsStorageService = inject(NaiveRagDocumentsStorageService);
    private pollingService = inject(NaiveRagPollingService);
    private ragConfiguration = viewChild.required(NaiveRagConfigurationComponent);
    indexingDisabled = computed(() => !this.ragConfiguration().filteredAndCheckedDocIds().length);

    constructor() {
        super();

        this.destroyRef.onDestroy(() => this.pollingService.stopPolling());

        toObservable(this.documentsStorageService.documents)
            .pipe(
                filter((docs) => docs.length > 0),
                take(1),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((docs) => {
                const indexingIds = docs
                    .filter((d) => d.status === 'chunking' || d.status === 'indexing')
                    .map((d) => d.naive_rag_document_id);
                if (indexingIds.length) {
                    this.pollingService.pollDocumentStatuses(this.data.ragId, indexingIds);
                }
            });
    }

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
                    this.naiveRagService.startIndexing({
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
                    this.pollingService.pollDocumentStatuses(this.data.ragId, configIds);
                },
                error: () => this.toast.error('Files re-indexing failed'),
            });
    }
}
