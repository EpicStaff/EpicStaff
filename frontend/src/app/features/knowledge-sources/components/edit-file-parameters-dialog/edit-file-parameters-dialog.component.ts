import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, signal, ViewChild } from '@angular/core';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';

import { NaiveRagChunkStrategy } from '../../enums/naive-rag-chunk-strategy';
import { NaiveRagAdditionalParams, UpdateNaiveRagDocumentDtoRequest } from '../../models/naive-rag-document.model';
import { NaiveRagDocumentsStorageService } from '../../services/naive-rag-documents-storage.service';
import { DocumentChunksSectionComponent } from '../document-chunks-section/document-chunks-section.component';
import { TableDocument } from '../naive-rag-configuration/configuration-table/configuration-table.interface';
import { DocumentConfigComponent } from './document-config/document-config.component';

@Component({
    selector: 'app-edit-file-parameters-dialog',
    templateUrl: './edit-file-parameters-dialog.component.html',
    styleUrls: ['./edit-file-parameters-dialog.component.scss'],
    imports: [AppSvgIconComponent, DocumentConfigComponent, DocumentChunksSectionComponent, ButtonComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditFileParametersDialogComponent {
    private dialogRef = inject(DialogRef);
    private documentsStorageService = inject(NaiveRagDocumentsStorageService);
    readonly data: { ragId: number; collectionId: number; ragDocumentId: number; allDocumentIds: number[] } =
        inject(DIALOG_DATA);

    @ViewChild('chunksSection', { static: true }) chunksSection!: DocumentChunksSectionComponent;
    @ViewChild('formSection', { static: true }) formSection!: DocumentConfigComponent;

    documents = this.documentsStorageService.documents;
    selectedDocumentId = signal<number>(this.data.ragDocumentId);

    document = computed<TableDocument>(
        () => this.documents().find((d) => d.naive_rag_document_id === this.selectedDocumentId())!
    );
    currentIndex = computed(() => this.data.allDocumentIds.indexOf(this.selectedDocumentId()));
    isPrevDisabled = computed(() => this.currentIndex() <= 0);
    isNextDisabled = computed(
        () => this.currentIndex() === -1 || this.currentIndex() >= this.data.allDocumentIds.length - 1
    );

    nextDocument() {
        const index = this.currentIndex();
        if (index === -1 || index >= this.data.allDocumentIds.length - 1) return;

        this.captureFormAsPending(this.selectedDocumentId());
        this.selectedDocumentId.set(this.data.allDocumentIds[index + 1]);
    }

    prevDocument() {
        const index = this.currentIndex();
        if (index <= 0) return;

        this.captureFormAsPending(this.selectedDocumentId());
        this.selectedDocumentId.set(this.data.allDocumentIds[index - 1]);
    }

    onShowChunks() {
        const documentId = this.selectedDocumentId();
        if (!this.captureFormAsPending(documentId)) return;
        this.chunksSection.runChunking();
    }

    onClose() {
        this.captureFormAsPending(this.selectedDocumentId());
        this.dialogRef.close();
    }

    private captureFormAsPending(documentId: number): boolean {
        const strategy = this.formSection.selectedStrategy() as NaiveRagChunkStrategy | null;
        const form = this.formSection.form;
        const mainParams = form.get('strategyParams')?.get('mainParams');
        const additionalParams = form.get('strategyParams')?.get('additionalParams');

        if (!mainParams || !additionalParams || !strategy) return false;
        if (mainParams.invalid || additionalParams.invalid) return false;

        const strategyChanged = strategy !== this.document().chunk_strategy;
        const userEdited = mainParams.dirty || additionalParams.dirty || strategyChanged;
        if (!userEdited) return true;

        const baseline = this.document();
        const baselineAdditional = baseline.additional_params;
        const baselineStrategyBlock = (baselineAdditional?.[strategy] ?? {}) as Record<string, unknown>;

        const patch: UpdateNaiveRagDocumentDtoRequest = {
            chunk_strategy: strategy,
            ...mainParams.value,
            additional_params: {
                ...baselineAdditional,
                [strategy]: {
                    ...baselineStrategyBlock,
                    ...(additionalParams.value as Record<string, unknown>),
                },
            } as Partial<NaiveRagAdditionalParams>,
        };

        this.documentsStorageService.setPendingFields(documentId, patch);
        return true;
    }
}
