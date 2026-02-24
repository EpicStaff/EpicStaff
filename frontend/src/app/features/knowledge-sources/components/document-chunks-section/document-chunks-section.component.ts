import { NgTemplateOutlet } from "@angular/common";
import { ChangeDetectionStrategy, Component, computed, effect, inject, input } from "@angular/core";
import { AppIconComponent, ButtonComponent, SpinnerComponent } from "@shared/components";
import { EMPTY } from "rxjs";
import { switchMap } from "rxjs/operators";
import { NaiveRagDocumentsStorageService } from "../../services/naive-rag-documents-storage.service";
import { ChunkPreviewComponent } from "./chunk-preview/chunk-preview.component";

@Component({
    selector: 'app-document-chunks-section',
    templateUrl: './document-chunks-section.component.html',
    styleUrls: ['./document-chunks-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppIconComponent,
        ButtonComponent,
        ChunkPreviewComponent,
        SpinnerComponent,
        NgTemplateOutlet
    ]
})
export class DocumentChunksSectionComponent {
    private chunksStorageService = inject(NaiveRagDocumentsStorageService);

    naiveRagId = input.required<number>();
    selectedDocumentId = input<number | null>(null);

    selectedDocState = computed(() => {
        const id = this.selectedDocumentId();
        if (!id) return;
        return this.chunksStorageService.documentStates().get(id);
    });

    constructor() {
        effect(() => {
            const document = this.selectedDocState();
            if (!document) return;

            if (document.status === 'chunked') {
                this.chunksStorageService.fetchChunks(this.naiveRagId(), document.id).subscribe();
            }
        });
    }

    runChunking() {
        const documentId = this.selectedDocumentId();
        if (!documentId) return;

        this.chunksStorageService.runChunking(this.naiveRagId(), documentId).pipe(
            switchMap(() => {
                const state = this.chunksStorageService.documentStates().get(documentId);
                if (!state) return EMPTY;

                // prevent chunks fetching if document was updated
                if (state.status === 'chunks_outdated') return EMPTY;

                // prevent chunks fetching if user select other document
                if (this.selectedDocumentId() !== documentId) return EMPTY;

                return this.chunksStorageService.fetchChunks(this.naiveRagId(), documentId);
            })
        ).subscribe();
    }
}
