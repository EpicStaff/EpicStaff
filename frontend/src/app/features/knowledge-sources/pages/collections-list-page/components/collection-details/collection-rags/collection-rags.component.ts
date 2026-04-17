import { Dialog } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, input } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent } from '@shared/components';
import { throwError } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../../../../services/notifications';
import { CreateCollectionDialogComponent } from '../../../../../components/create-collection-dialog/create-collection-dialog.component';
import { GraphRagConfigurationDialog } from '../../../../../components/rag-configuration-dialog/graph-rag-configuration-dialog/graph-rag-configuration-dialog.component';
import { NaiveRagConfigurationDialog } from '../../../../../components/rag-configuration-dialog/naive-rag-configuration-dialog/naive-rag-configuration-dialog.component';
import { RagConfigurationDialogComponent } from '../../../../../components/rag-configuration-dialog/rag-configuration-dialog.component';
import { RagType } from '../../../../../models/base-rag.model';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';

@Component({
    selector: 'app-collection-details-rags',
    templateUrl: 'collection-rags.component.html',
    styleUrls: ['./collection-rags.component.scss'],
    imports: [AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionRagsComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private collectionsStorageService = inject(CollectionsStorageService);
    private toastService = inject(ToastService);

    collection = input.required<CreateCollectionDtoResponse>();

    onConfigureNaiveRag(type: RagType): void {
        const ragConfigurations = this.collection().rag_configurations;
        const ragConfig = ragConfigurations.find((i) => i.rag_type === type);

        if (!ragConfigurations.length || !ragConfig) {
            this.openCollectionModal(type);
            return;
        }

        if (type === 'naive') {
            this.openRagConfigurationDialog(ragConfig.rag_id, NaiveRagConfigurationDialog);
            return;
        }

        if (type === 'graph') {
            this.openRagConfigurationDialog(ragConfig.rag_id, GraphRagConfigurationDialog);
            return;
        }
    }

    private openCollectionModal(forceType: RagType): void {
        const dialog = this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { collection_id: this.collection().collection_id, forceType },
            disableClose: true,
        });

        dialog.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    return this.collectionsStorageService.getFullCollection(this.collection().collection_id, true);
                }),
                catchError((error) => {
                    this.toastService.error('Failed to get collection data');
                    return throwError(() => error);
                })
            )
            .subscribe();
    }

    private openRagConfigurationDialog(
        ragId: number,
        dialogComponent: ComponentType<RagConfigurationDialogComponent>
    ): void {
        const dialog = this.dialog.open(dialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { ragId },
            disableClose: true,
        });

        dialog.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }
}
