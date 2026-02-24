import {ChangeDetectionStrategy, Component, DestroyRef, inject} from "@angular/core";
import {CreateCollectionDtoResponse} from "../../models/collection.model";
import {DIALOG_DATA, DialogRef} from "@angular/cdk/dialog";
import {ButtonComponent} from "@shared/components";
import {RagConfigurationComponent} from "../rag-configuration/rag-configuration.component";
import {NaiveRagService} from "../../services/naive-rag.service";
import {takeUntilDestroyed} from "@angular/core/rxjs-interop";
import {ToastService} from "../../../../services/notifications";

@Component({
    selector: 'app-naive-rag-configuration-dialog',
    templateUrl: './naive-rag-configuration-dialog.component.html',
    styleUrls: ['./naive-rag-configuration-dialog.component.scss'],
    imports: [
        RagConfigurationComponent,
        ButtonComponent
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class NaiveRagConfigurationDialog {
    data: { collection: CreateCollectionDtoResponse, ragId: number } = inject(DIALOG_DATA);
    private destroyRef = inject(DestroyRef);
    private dialogRef = inject(DialogRef);
    private naiveRagService = inject(NaiveRagService);
    private toast = inject(ToastService);

    onClose(): void {
        this.dialogRef.close();
    }

    runIndexing(): void {
        this.naiveRagService.startIndexing({
            rag_id: this.data.ragId,
            rag_type: 'naive'
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.toast.success('Files re-indexed successfully'),
                error: () => this.toast.error('Files re-indexing failed'),
            })
    }
}
