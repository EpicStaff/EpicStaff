import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal, ViewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ConfirmationDialogService, StepConfig } from '@shared/components';
import { AppSvgIconComponent, StepperComponent } from '@shared/components';
import { filter, Observable, of } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { RAG_TYPE_CONFIG } from '../../constants/constants';
import { getIndexingConfirmationData } from '../../helpers/get-indexing-confirmation-data.util';
import { RagType } from '../../models/base-rag.model';
import { CreateCollectionStep } from '../../models/collection.model';
import { DisplayedListDocument } from '../../models/document.model';
import { RagConfiguration } from '../../models/rag-configuration';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { RagDeleteRegistryService } from '../../services/rag-delete-registry.service';
import { StepSelectRagComponent } from './components/steps/step-select-rag/step-select-rag.component';
import { StepUploadFilesComponent } from './components/steps/step-upload-files/step-upload-files.component';
import { RagCreationStrategy } from './factory/interfaces/rag-creation-strategy.interface';
import { RagStrategyFactory } from './factory/rag-creation.factory';

export interface CreateCollectionDialogData {
    collection_id: number;
    isUpdate?: boolean;
    initialDocumentId?: number;
}

@Component({
    selector: 'app-create-collection-dialog',
    templateUrl: './create-collection-dialog.component.html',
    styleUrls: ['./create-collection-dialog.component.scss'],
    imports: [
        ButtonComponent,
        StepperComponent,
        StepUploadFilesComponent,
        StepSelectRagComponent,
        AppSvgIconComponent,
        NgComponentOutlet,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateCollectionDialogComponent {
    data: CreateCollectionDialogData = inject(DIALOG_DATA);

    private destroyRef = inject(DestroyRef);
    private dialogRef = inject(DialogRef);
    private factory = inject(RagStrategyFactory);
    private collectionsStorageService = inject(CollectionsStorageService);
    private toastService = inject(ToastService);
    private confirmation = inject(ConfirmationDialogService);
    private ragDeleteRegistry = inject(RagDeleteRegistryService);

    currentStepIndex = signal(0);
    selectedRagType = signal<RagType | null>(null);
    selectedEmbedder = signal<number | null>(null);
    selectedLLM = signal<number | null>(null);
    selectedDocuments = signal<DisplayedListDocument[]>([]);

    private strategy = signal<RagCreationStrategy | null>(null);

    collection = computed(
        () => this.collectionsStorageService.fullCollections().find((c) => c.collection_id === this.data.collection_id)!
    );

    canProceedSelectRag = computed(() => {
        const type = this.selectedRagType();
        if (!type || !this.selectedEmbedder()) return false;
        if (type === 'naive') return true;
        return !!this.selectedLLM();
    });

    steps = computed<StepConfig[]>(() => [
        {
            id: CreateCollectionStep.UPLOAD_FILES,
            label: 'Upload files',
            proceedLabel: 'Next',
            onProceed: () => of(true),
            canProceed: () =>
                this.selectedDocuments().length > 0 &&
                this.selectedDocuments().every((d) => d.isValidType && d.isValidSize),
        },
        {
            id: CreateCollectionStep.SELECT_RAG,
            label: 'Select RAG',
            proceedLabel: 'Next',
            onProceed: () => this.handleCreateRag(),
            canProceed: () => this.canProceedSelectRag(),
        },
        {
            id: CreateCollectionStep.CONFIGURE,
            label: 'Configure',
            proceedLabel: 'Run Indexing',
            onProceed: () => this.handleIndexing(),
            canProceed: () => this.strategy()?.canIndex() ?? false,
        },
    ]);

    currentStep = computed(() => this.steps()[this.currentStepIndex()]);
    nextDisabled = computed(() => !this.currentStep().canProceed());
    nextText = computed(() => this.currentStep().proceedLabel);
    stepLabels = computed(() => this.steps().map((s) => s.label));

    configurationComponent = computed(() => this.strategy()?.getConfigurationComponent() ?? null);

    configurationInputs = computed(() => this.strategy()?.getConfigurationInputs());

    @ViewChild(NgComponentOutlet, { static: false })
    private strategyComponent!: NgComponentOutlet;

    prevStep() {
        this.currentStepIndex.update((i) => Math.max(i - 1, 0));
    }

    nextStep() {
        if (!this.currentStep().canProceed()) return;

        this.currentStep()
            .onProceed()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((success) => {
                if (!success) return;

                const last = this.steps().length - 1;

                this.currentStepIndex.update((i) => {
                    if (i >= last) {
                        return i;
                    }
                    return i + 1;
                });
            });
    }

    private handleCreateRag(): Observable<boolean> {
        const type = this.selectedRagType();
        const embedderId = this.selectedEmbedder();
        const collectionId = this.data.collection_id;
        if (!type || !embedderId) return of(false);

        const existingRag = this.collection().rag_configurations.find((r) => r.rag_type === type);

        const createRag$ = () => {
            const strategy = this.factory.create(type);
            this.strategy.set(strategy);
            return strategy.create(collectionId, embedderId, this.selectedLLM() ?? undefined).pipe(
                catchError(() => {
                    this.toastService.error('Failed to create RAG');
                    return of(false);
                })
            );
        };

        // delete old rag before creating new
        if (existingRag) {
            const ragName = RAG_TYPE_CONFIG[type].name;
            return this.confirmation
                .confirm({
                    title: `Replace ${ragName}`,
                    message: `Existing <strong>${ragName}</strong> and its indexed documents will be permanently deleted before creating a new one.`,
                    type: 'warning',
                    cancelText: 'Cancel',
                    confirmText: 'Replace',
                })
                .pipe(
                    filter((result) => result === true),
                    switchMap(() => this.ragDeleteRegistry.deleteRag(type, existingRag.rag_id)),
                    switchMap(() => createRag$()),
                    catchError(() => {
                        this.toastService.error('Failed to replace RAG');
                        return of(false);
                    })
                );
        }

        return createRag$();
    }

    private handleIndexing(): Observable<boolean> {
        const strategy = this.strategy();
        if (!strategy || !this.strategyComponent) return of(false);

        const componentInstance: RagConfiguration = this.strategyComponent['_componentRef'].instance;
        const componentData = componentInstance.getConfigurationData();
        const configIds = componentInstance.getDocumentConfigIds();

        if (!componentData) {
            return of(false);
        }

        let indexingDocs = componentInstance.getIndexingDocuments();
        if (!indexingDocs.length) {
            indexingDocs = this.selectedDocuments().map((d) => ({ fileName: d.file_name, wasIndexed: false }));
        }

        return this.confirmation.confirm(getIndexingConfirmationData(indexingDocs)).pipe(
            takeUntilDestroyed(this.destroyRef),
            filter((result) => result === true),
            switchMap(() =>
                strategy.startIndexing({ ...componentData, configIds }).pipe(
                    catchError(() => {
                        this.toastService.error('Indexing failed');
                        return of(false);
                    })
                )
            )
        );
    }

    onClose() {
        this.strategy()?.dispose?.();
        this.dialogRef.close();
    }

    protected readonly CreateCollectionStep = CreateCollectionStep;
}
