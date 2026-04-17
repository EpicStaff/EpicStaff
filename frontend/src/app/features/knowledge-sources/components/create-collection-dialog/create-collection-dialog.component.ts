import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal, ViewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { Observable, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { RagType } from '../../models/base-rag.model';
import { CreateCollectionStep } from '../../models/collection.model';
import { DisplayedListDocument } from '../../models/document.model';
import { RagConfiguration } from '../../models/rag-configuration';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { StepperComponent } from './components/stepper/stepper.component';
import { StepSelectRagComponent } from './components/steps/step-select-rag/step-select-rag.component';
import { StepUploadFilesComponent } from './components/steps/step-upload-files/step-upload-files.component';
import { RagCreationStrategy } from './factory/interfaces/rag-creation-strategy.interface';
import { RagStrategyFactory } from './factory/rag-creation.factory';

export interface StepConfig {
    id: CreateCollectionStep;
    label: string;
    onProceed: () => Observable<boolean>;
    canProceed: () => boolean;
    proceedLabel: string;
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
        NgComponentOutlet,
        AppSvgIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateCollectionDialogComponent {
    data: { collection_id: number; forceType: RagType | undefined } = inject(DIALOG_DATA);

    private destroyRef = inject(DestroyRef);
    private dialogRef = inject(DialogRef);
    private factory = inject(RagStrategyFactory);
    private collectionsStorageService = inject(CollectionsStorageService);
    private toastService = inject(ToastService);

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
            proceedLabel: 'Finish Creation',
            onProceed: () => this.handleFinish(),
            canProceed: () => true,
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
                        this.onClose();
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

        const strategy = this.factory.create(type);
        this.strategy.set(strategy);

        return strategy.create(collectionId, embedderId, this.selectedLLM() ?? undefined).pipe(
            catchError(() => {
                this.toastService.error('Failed to create RAG');
                return of(false);
            })
        );
    }

    private handleFinish(): Observable<boolean> {
        const strategy = this.strategy();
        if (!strategy || !this.strategyComponent) return of(false);

        const componentInstance: RagConfiguration = this.strategyComponent['_componentRef'].instance;
        const componentData = componentInstance.getConfigurationData();

        if (!componentData) {
            return of(false);
        }

        return strategy.startIndexing(componentData).pipe(
            catchError(() => {
                this.toastService.error('Indexing failed');
                return of(false);
            })
        );
    }

    onClose() {
        this.dialogRef.close();
    }

    protected readonly CreateCollectionStep = CreateCollectionStep;
}
