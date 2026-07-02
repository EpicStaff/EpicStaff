import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService } from '@shared/components';
import { filter, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { RagType } from '../../models/base-rag.model';
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

    protected abstract onClose(): void;
    protected abstract runIndexing(): void;

    stopIndexing() {
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
                next: () => this.toast.success('Indexing stopped'),
                error: () => this.toast.error('Indexing stop failed'),
            });
    }
}
