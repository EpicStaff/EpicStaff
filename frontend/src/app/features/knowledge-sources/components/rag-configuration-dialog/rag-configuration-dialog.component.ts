import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { Observable, of } from 'rxjs';
import { filter, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { getIndexingEstimateHtml } from '../../helpers/format-indexing-estimate.util';
import { getIndexingConfirmationData, IndexingDocumentInfo } from '../../helpers/get-indexing-confirmation-data.util';
import { RagType } from '../../models/base-rag.model';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { RagIndexingService } from '../../services/rag-indexing.service';

@Component({
    changeDetection: ChangeDetectionStrategy.Eager,
    template: '',
})
export abstract class RagConfigurationDialogComponent {
    protected data: { ragId: number; ragType: RagType; collectionId: number } = inject(DIALOG_DATA);
    protected destroyRef = inject(DestroyRef);
    protected dialogRef = inject(DialogRef);
    protected toast = inject(ToastService);
    protected confirmation = inject(ConfirmationDialogService);
    protected ragIndexingService = inject(RagIndexingService);
    protected pollingService = inject(KnowledgeSourcesPollingService);

    protected readonly isPreparingIndexing = signal(false);

    protected abstract onClose(): void;
    protected abstract runIndexing(): void;

    stopIndexing(documentConfigIds?: number[]) {
        this.confirmation
            .confirm({
                title: 'Stop indexing',
                message: `Do you want to stop indexing?`,
                type: 'warning',
                cancelText: 'Cancel',
                confirmText: 'Stop indexing',
            })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                filter((result) => result === true),
                switchMap(() =>
                    this.ragIndexingService.stopIndexing({
                        rag_id: this.data.ragId,
                        rag_type: this.data.ragType,
                    })
                )
            )
            .subscribe({
                next: () => {
                    this.toast.success('Indexing stop requested');
                    this.pollingService.discardTrackedProcessingIds(documentConfigIds ?? []);
                },
                error: () => this.toast.error('Indexing stop failed'),
            });
    }

    protected confirmIndexing(
        documents: IndexingDocumentInfo[],
        configIds: number[],
        hasUnsavedIndexConfig = false
    ): Observable<ConfirmationResult> {
        const estimate$ = configIds.length
            ? this.ragIndexingService.estimateIndexingOrNull({
                  rag_id: this.data.ragId,
                  rag_type: this.data.ragType,
                  document_config_ids: configIds,
              })
            : of(null);

        return estimate$.pipe(
            switchMap((estimate) =>
                this.confirmation.confirm(
                    getIndexingConfirmationData(documents, getIndexingEstimateHtml(estimate, hasUnsavedIndexConfig))
                )
            )
        );
    }
}
