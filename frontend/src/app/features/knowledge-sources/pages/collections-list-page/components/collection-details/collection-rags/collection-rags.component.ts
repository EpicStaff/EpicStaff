import { Dialog } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, input } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ConfirmationDialogService } from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';
import { filter, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../../../../services/notifications';
import { GraphRagConfigurationDialog } from '../../../../../components/rag-configuration-dialog/graph-rag-configuration-dialog/graph-rag-configuration-dialog.component';
import { NaiveRagConfigurationDialog } from '../../../../../components/rag-configuration-dialog/naive-rag-configuration-dialog/naive-rag-configuration-dialog.component';
import { RagConfigurationDialogComponent } from '../../../../../components/rag-configuration-dialog/rag-configuration-dialog.component';
import { RAG_STATUS_CONFIG, RAG_TYPE_CONFIG } from '../../../../../constants/constants';
import { RagType } from '../../../../../models/base-rag.model';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { NaiveRagDocumentsStorageService } from '../../../../../services/naive-rag-documents-storage.service';
import { RagDeleteRegistryService } from '../../../../../services/rag-delete-registry.service';

@Component({
    selector: 'app-collection-details-rags',
    templateUrl: 'collection-rags.component.html',
    styleUrls: ['./collection-rags.component.scss'],
    imports: [AppSvgIconComponent, MATERIAL_FORMS],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionRagsComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private collectionsStorageService = inject(CollectionsStorageService);
    private confirmationService = inject(ConfirmationDialogService);
    private ragDeleteRegistry = inject(RagDeleteRegistryService);
    private naiveRagDocumentsStorage = inject(NaiveRagDocumentsStorageService);

    collection = input.required<CreateCollectionDtoResponse>();

    ragTypeConfig = RAG_TYPE_CONFIG;
    ragStatusConfig = RAG_STATUS_CONFIG;

    onConfigureRag(type: RagType): void {
        const ragConfigurations = this.collection().rag_configurations;
        const ragConfig = ragConfigurations.find((i) => i.rag_type === type);

        if (type === 'naive') {
            this.openRagConfigurationDialog(ragConfig!.rag_id, NaiveRagConfigurationDialog);
            return;
        }

        if (type === 'graph') {
            this.openRagConfigurationDialog(ragConfig!.rag_id, GraphRagConfigurationDialog);
            return;
        }
    }

    onDeleteRag(type: RagType, ragId: number): void {
        if (type !== 'naive') return;

        const ragName = this.ragTypeConfig[type].name;

        this.confirmationService
            .confirmDelete(ragName)
            .pipe(
                filter((result) => result === true),
                switchMap(() => this.ragDeleteRegistry.deleteRag(type, ragId)),
                switchMap(() =>
                    this.collectionsStorageService.getFullCollection(this.collection().collection_id, true)
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => {
                this.toast.success('RAG deleted');
                this.naiveRagDocumentsStorage.clear();
            });
    }

    private openRagConfigurationDialog(
        ragId: number,
        dialogComponent: ComponentType<RagConfigurationDialogComponent>
    ): void {
        const collectionId = this.collection().collection_id;
        const dialog = this.dialog.open(dialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { ragId, collectionId },
            disableClose: true,
        });

        dialog.closed
            .pipe(
                switchMap(() => this.collectionsStorageService.getFullCollection(collectionId, true)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }
}
