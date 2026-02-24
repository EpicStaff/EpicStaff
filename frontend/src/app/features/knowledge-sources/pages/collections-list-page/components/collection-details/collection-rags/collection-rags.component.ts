import {ChangeDetectionStrategy, Component, DestroyRef, inject, input} from "@angular/core";
import {AppIconComponent} from "@shared/components";
import {Dialog} from "@angular/cdk/dialog";
import {
    NaiveRagConfigurationDialog
} from "../../../../../components/naive-rag-configuration-dialog/naive-rag-configuration-dialog.component";
import {CreateCollectionDtoResponse} from "../../../../../models/collection.model";
import {
    CreateCollectionDialogComponent
} from "../../../../../components/create-collection-dialog/create-collection-dialog.component";
import {takeUntilDestroyed} from "@angular/core/rxjs-interop";
import {CollectionsStorageService} from "../../../../../services/collections-storage.service";
import {catchError, switchMap} from "rxjs/operators";
import {ToastService} from "../../../../../../../services/notifications";
import {throwError} from "rxjs";

@Component({
    selector: 'app-collection-details-rags',
    templateUrl: 'collection-rags.component.html',
    styleUrls: ['./collection-rags.component.scss'],
    imports: [
        AppIconComponent
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CollectionRagsComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private collectionsStorageService = inject(CollectionsStorageService);
    private toastService = inject(ToastService);

    collection = input.required<CreateCollectionDtoResponse>();

    onConfigureNaiveRag() {
        if (!this.collection().rag_configurations.length) {
            this.openCollectionModal();
            return;
        }

        const naiveRag = this.collection().rag_configurations.find(i => i.rag_type === 'naive');

        if (!naiveRag) return;

        const dialog = this.dialog.open(NaiveRagConfigurationDialog, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: {
                collection: this.collection(),
                ragId: naiveRag.rag_id
            },
            disableClose: true
        });

        dialog.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
            )
            .subscribe()
    }

    private openCollectionModal(): void {
        const dialog = this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: this.collection().collection_id,
            disableClose: true
        });

        dialog.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    return this.collectionsStorageService.getFullCollection(this.collection().collection_id, true)
                }),
                catchError((error) => {
                    this.toastService.error('Failed to get collection data')
                    return throwError(() => error)
                })
            )
            .subscribe();
    }
}
