import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnDestroy,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, SpinnerComponent } from '@shared/components';
import { EMPTY, Subject } from 'rxjs';
import { switchMap, takeUntil } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { ChunkDeepLinkService } from '../../services/chunk-deep-link.service';
import { ChunkSearchService } from '../../services/chunk-search.service';
import { NaiveRagDocumentsStorageService } from '../../services/naive-rag-documents-storage.service';
import { ChunkPreviewComponent } from './chunk-preview/chunk-preview.component';
import { ChunkSearchBarComponent, ChunkSearchParams } from './chunk-search-bar/chunk-search-bar.component';

@Component({
    selector: 'app-document-chunks-section',
    templateUrl: './document-chunks-section.component.html',
    styleUrls: ['./document-chunks-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        ChunkPreviewComponent,
        ChunkSearchBarComponent,
        SpinnerComponent,
        NgTemplateOutlet,
    ],
})
export class DocumentChunksSectionComponent implements OnDestroy {
    private chunksStorageService = inject(NaiveRagDocumentsStorageService);
    private chunkSearchService = inject(ChunkSearchService);
    private deepLinkService = inject(ChunkDeepLinkService);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);

    naiveRagId = input.required<number>();
    collectionId = input.required<number>();
    selectedDocumentId = input<number | null>(null);

    chunkSearchState = this.chunkSearchService.chunkSearchState;

    private cancelChunking$ = new Subject<void>();

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
                const deepLinkChunkId = this.deepLinkService.pending()?.chunkId ?? 0;
                this.chunksStorageService.fetchChunks(this.naiveRagId(), document.id, deepLinkChunkId).subscribe();
            }

            if (document.status === 'new' && this.deepLinkService.pending()) {
                this.runChunking();
            }
        });

        // Clear search when document changes
        effect(() => {
            this.selectedDocumentId();
            this.chunkSearchService.clearSearch();
        });
    }

    runChunking() {
        const documentId = this.selectedDocumentId();
        if (!documentId) return;

        this.chunkSearchService.clearSearch();

        this.chunksStorageService
            .runChunking(this.naiveRagId(), documentId)
            .pipe(
                takeUntil(this.cancelChunking$),
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    const state = this.chunksStorageService.documentStates().get(documentId);
                    if (!state) return EMPTY;

                    if (state.status === 'chunks_outdated') return EMPTY;
                    if (this.selectedDocumentId() !== documentId) return EMPTY;

                    const deepLinkChunkId = this.deepLinkService.pending()?.chunkId ?? 0;
                    return this.chunksStorageService.fetchChunks(this.naiveRagId(), documentId, deepLinkChunkId);
                })
            )
            .subscribe();
    }

    stopChunking() {
        const documentId = this.selectedDocumentId();
        if (!documentId) return;

        this.cancelChunking$.next();
        this.chunksStorageService
            .stopChunking(this.naiveRagId(), documentId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.toast.success('Chunking stopped'),
                error: () => this.toast.error('Chunking stop failed'),
            });
    }

    onSearchChange(params: ChunkSearchParams): void {
        const docId = this.selectedDocumentId();
        const ragId = this.naiveRagId();
        if (!docId) return;

        this.chunkSearchService.updateSearchParams(params.idFilter, params.textQuery);
        const search = this.chunkSearchService.chunkSearchState();

        switch (search.mode) {
            case 'none':
                this.chunkSearchService.clearSearch();
                break;
            case 'id_only':
                this.chunkSearchService
                    .fetchSingleChunkById(ragId, docId, params.idFilter as number)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe();
                break;
            case 'id_and_text':
                this.chunkSearchService
                    .fetchSingleChunkById(ragId, docId, params.idFilter as number)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe();
                break;
            case 'text_only':
                this.chunkSearchService
                    .searchChunksByText(ragId, docId, params.textQuery)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe();
                break;
        }
    }

    onPrevMatch(): void {
        const search = this.chunkSearchService.chunkSearchState();
        if (search.currentMatchIndex > 1) {
            this.chunkSearchService.setCurrentMatchIndex(search.currentMatchIndex - 1);
        }
    }

    onNextMatch(): void {
        const search = this.chunkSearchService.chunkSearchState();
        if (search.currentMatchIndex < search.totalMatches) {
            this.chunkSearchService.setCurrentMatchIndex(search.currentMatchIndex + 1);
        }
    }

    ngOnDestroy() {
        this.deepLinkService.clearUrl();
    }
}
