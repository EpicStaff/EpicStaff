import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService } from '@shared/components';
import { filter, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { RagType } from '../../models/base-rag.model';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { RagIndexingService } from '../../services/rag-indexing.service';

@Component({
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
                        document_config_ids: documentConfigIds,
                    })
                )
            )
            .subscribe({
                next: () => {
                    this.toast.success('Indexing stop triggered');
                    this.pollingService.discardTrackedProcessingIds(documentConfigIds ?? []);
                },
                error: () => this.toast.error('Indexing stop failed'),
            });
    }
}
