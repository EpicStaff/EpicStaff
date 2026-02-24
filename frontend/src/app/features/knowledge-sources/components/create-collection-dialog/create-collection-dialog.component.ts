import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from "@angular/core";
import { ButtonComponent, AppIconComponent } from "@shared/components";
import { DIALOG_DATA, DialogRef } from "@angular/cdk/dialog";
import { CreateCollectionStep } from "../../models/collection.model";
import { StepUploadFilesComponent } from "./steps/step-upload-files/step-upload-files.component";
import { StepSelectRagComponent } from "./steps/step-select-rag/step-select-rag.component";
import { StepperComponent } from "./stepper/stepper.component";
import { DisplayedListDocument } from "../../models/document.model";
import { RagConfigurationComponent } from "../rag-configuration/rag-configuration.component";
import { NaiveRagService } from "../../services/naive-rag.service";
import { catchError, map, tap } from "rxjs/operators";
import { Observable, of } from "rxjs";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { RagType } from "../../models/naive-rag.model";
import { ToastService } from "../../../../services/notifications";
import { CollectionsStorageService } from "../../services/collections-storage.service";

export interface StepConfig {
    id: CreateCollectionStep;
    label: string;
    onProceed: () => Observable<boolean>;
    canProceed: () => boolean;
    proceedLabel: string;
}

@Component({
    selector: 'app-create-collection-dialog',
    templateUrl: 'create-collection-dialog.component.html',
    styleUrls: ['create-collection-dialog.component.scss'],
    imports: [
        ButtonComponent,
        AppIconComponent,
        StepUploadFilesComponent,
        StepSelectRagComponent,
        StepperComponent,
        RagConfigurationComponent,
        AppIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CreateCollectionDialogComponent {
    collectionId: number = inject(DIALOG_DATA);
    private destroyRef = inject(DestroyRef);
    private dialogRef = inject(DialogRef);
    private collectionsStorageService = inject(CollectionsStorageService);
    private naiveRagService = inject(NaiveRagService);
    private toastService = inject(ToastService);

    collection = computed(() => {
        return this.collectionsStorageService.fullCollections().find(
            ({ collection_id }) => collection_id === this.collectionId
        )!;
    })

    steps = signal<StepConfig[]>([
        {
            id: CreateCollectionStep.UPLOAD_FILES,
            label: 'Upload files',
            proceedLabel: 'Next',
            onProceed: () => of(true),
            canProceed: () =>
                this.selectedDocuments().length > 0 &&
                this.selectedDocuments().every(d => d.isValidType && d.isValidSize),
        },
        {
            id: CreateCollectionStep.SELECT_RAG,
            label: 'Select RAG',
            proceedLabel: 'Next',
            onProceed: () => this.createRag(),
            canProceed: () => !!this.selectedRagType() && !!this.selectedEmbedder(),
        },
        {
            id: CreateCollectionStep.CONFIGURE,
            label: 'Configure',
            proceedLabel: 'Finish Creation',
            onProceed: () => this.startIndexing(),
            canProceed: () => true,
        },
    ]);

    currentStepIndex = signal(0);
    currentStep = computed(() => this.steps()[this.currentStepIndex()]);
    stepLabels = computed(() =>
        this.steps().map(s => s.label)
    );

    nextStepDisabled = computed(() =>
        !this.currentStep().canProceed()
    );

    nextButtonText = computed(() =>
        this.currentStep().proceedLabel
    );

    selectedRagType = signal<RagType | null>(null);
    selectedEmbedder = signal<number | null>(null);
    selectedDocuments = signal<DisplayedListDocument[]>([]);
    naiveRagId = signal<number | null>(null);

    prevStep() {
        this.currentStepIndex.update(i => Math.max(i - 1, 0));
    }

    nextStep() {
        if (!this.currentStep().canProceed()) return;

        this.currentStep().onProceed().pipe(
            takeUntilDestroyed(this.destroyRef),
        ).subscribe({
            next: (v) => {
                if (!v) return;

                this.currentStepIndex.update(i => {
                    const lastIndex = this.steps().length - 1;

                    if (i >= lastIndex) {
                        this.onClose();
                        return i;
                    }

                    return i + 1;
                });
            }
        });
    }

    createRag(): Observable<boolean> {
        const id = this.collectionId;
        const embedderId = this.selectedEmbedder();
        if (!embedderId) return of(false);

        return this.naiveRagService.createRagForCollection(id, embedderId).pipe(
            takeUntilDestroyed(this.destroyRef),
            tap(({ naive_rag }) => {
                this.naiveRagId.set(naive_rag.naive_rag_id);
            }),
            map(() => true),
            catchError(() => {
                this.toastService.error('Failed to create Rag for Collection');
                return of(false);
            })
        );
    }

    startIndexing(): Observable<boolean> {
        const ragType = this.selectedRagType();
        const ragId = this.naiveRagId();

        if (!ragType || !ragId) return of(false);

        return this.naiveRagService.startIndexing({
            rag_id: ragId,
            rag_type: ragType,
        }).pipe(
            takeUntilDestroyed(this.destroyRef),
            map(() => true),
            catchError(() => {
                this.toastService.error('RAG indexing failed');
                return of(false);
            })
        )
    }

    onClose(): void {
        this.dialogRef.close();
    }

    protected readonly CreateCollectionStep = CreateCollectionStep;
}
