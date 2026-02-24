import { Dialog } from "@angular/cdk/dialog";
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    OnInit,
    signal
} from "@angular/core";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { FormsModule } from "@angular/forms";
import {
    AppIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    SearchComponent,
} from "@shared/components";
import { EMPTY, groupBy, mergeMap, of, Subject } from "rxjs";
import { catchError, debounceTime, switchMap } from "rxjs/operators";

import { ToastService } from "../../../../services/notifications";
import { CreateCollectionDtoResponse } from "../../models/collection.model";
import { UpdateNaiveRagDocumentDtoRequest, } from "../../models/naive-rag-document.model";
import { NaiveRagDocumentsStorageService } from "../../services/naive-rag-documents-storage.service";
import { NaiveRagService } from "../../services/naive-rag.service";
import { DocumentChunksSectionComponent } from "../document-chunks-section/document-chunks-section.component";
import {
    EditFileParametersDialogComponent
} from "../edit-file-parameters-dialog/edit-file-parameters-dialog.component";
import { ConfigurationTableComponent } from "./configuration-table/configuration-table.component";
import { DocFieldChange, } from "./configuration-table/configuration-table.interface";

@Component({
    selector: 'app-rag-configuration',
    templateUrl: './rag-configuration.component.html',
    styleUrls: ['./rag-configuration.component.scss'],
    imports: [
        FormsModule,
        SearchComponent,
        ConfigurationTableComponent,
        AppIconComponent,
        ButtonComponent,
        DocumentChunksSectionComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class RagConfigurationComponent implements OnInit {
    private confirmationDialogService = inject(ConfirmationDialogService);
    private naiveRagService = inject(NaiveRagService);
    private destroyRef = inject(DestroyRef);
    private toastService = inject(ToastService);
    private documentsStorageService = inject(NaiveRagDocumentsStorageService);
    private dialog = inject(Dialog);

    naiveRagId = input.required<number>();
    collection = input.required<CreateCollectionDtoResponse>();

    searchTerm = signal<string>('');
    bulkBtnActive = signal<boolean>(false);
    selectedRagDocId = signal<number | null>(null);
    filteredAndCheckedDocIds = signal<number[]>([]);
    tuneChunkOpened = signal<boolean>(false);

    showBulkRow = computed(() => this.bulkBtnActive() && !!this.filteredAndCheckedDocIds().length);

    private docFieldChange$ = new Subject<DocFieldChange>();

    ngOnInit() {
        const id = this.naiveRagId();
        this.documentsStorageService.fetchDocumentConfigs(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                },
                error: (e) => {
                    this.toastService.error('Failed to fetch documents');
                    console.log(e);
                }
            });

        this.docFieldChange$.pipe(
            groupBy(change => change.documentId),
            mergeMap(group$ => group$.pipe(
                debounceTime(300),
                switchMap(change => this.documentsStorageService.updateDocumentField(id, change)
                    .pipe(
                        catchError((err) => {
                            const [error] = err.error?.errors;

                            this.toastService.error(`Update failed: ${error.reason}`);
                            return EMPTY;
                        }))),
            )),
            takeUntilDestroyed(this.destroyRef)
        ).subscribe(() => this.toastService.success('Document updated'));
    }

    onDocFieldChange(change: DocFieldChange) {
        this.docFieldChange$.next(change);
    }

    initDocuments() {
        const id = this.naiveRagId();

        this.naiveRagService.initializeDocuments(id)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(response => {
                    if (response && response.configs_created > 0) {
                        return this.documentsStorageService.fetchDocumentConfigs(id);
                    } else {
                        return EMPTY;
                    }
                }),
            )
            .subscribe({
                next: () => {},
                error: (e) => {
                    this.toastService.error('Failed to fetch documents');
                    console.log(e);
                }
            });
    }

    applyBulkEdit(dto: UpdateNaiveRagDocumentDtoRequest) {
        const config_ids = this.filteredAndCheckedDocIds();
        if (!config_ids.length) return;
        const id = this.naiveRagId();

        this.documentsStorageService.bulkEditDocConfigs(id, config_ids, dto)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (res) => this.toastService.success(res.message),
                error: (e) => console.log(e)
            });
    }

    applyBulkDelete() {
        const config_ids = this.filteredAndCheckedDocIds();
        if (!config_ids.length) return;

        this.confirmationDialogService.confirm({
            title: 'Confirm Deletion',
            message: `Are you sure you want to delete selected file(s)? <br> You can return them by clicking the 'Re-include Files' button.`,
            confirmText: 'Delete',
            cancelText: 'Cancel',
            type: 'info',
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.deleteDocConfigs(config_ids);
                }
            });
    }

    private deleteDocConfigs(config_ids: number[]) {
        const id = this.naiveRagId();

        this.documentsStorageService
            .bulkDeleteDocConfigs(id, config_ids)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                catchError(() => {
                    this.toastService.error('Documents delete failed');
                    return of();
                })
            )
            .subscribe({
                next: (res) => this.toastService.success(res.message),
                error: (e) => console.log(e),
            });
    }

    openTuneChunkModal({ragDocumentId, allDocumentIds}: {ragDocumentId: number, allDocumentIds: number[]}) {
        this.tuneChunkOpened.set(true);
        const dialogRef = this.dialog.open(EditFileParametersDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: {
                ragId: this.naiveRagId(),
                ragDocumentId,
                allDocumentIds,
            },
            disableClose: true
        });

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.tuneChunkOpened.set(false))
    }
}
