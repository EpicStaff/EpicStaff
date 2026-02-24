import { NgClass } from "@angular/common";
import {
    ChangeDetectionStrategy,
    Component,
    computed, DestroyRef, inject,
    input, NgZone, OnChanges, signal, SimpleChanges,
} from "@angular/core";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { FormsModule } from "@angular/forms";
import { MATERIAL_FORMS } from "@shared/material-forms";
import { take } from "rxjs";
import { calcLimit } from "../../../helpers/calculate-chunks-fetch-limit.util";
import {
    DocumentChunkingState,
    NaiveRagDocumentChunk
} from "../../../models/naive-rag-chunk.model";
import { NaiveRagDocumentsStorageService } from "../../../services/naive-rag-documents-storage.service";

interface DisplayedChunk {
    chunkIndex: number,
    overlap: string,
    text: string
}

@Component({
    selector: 'app-chunk-preview',
    templateUrl: './chunk-preview.component.html',
    styleUrls: ['./chunk-preview.component.scss'],
    imports: [
        NgClass,
        FormsModule,
        MATERIAL_FORMS,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ChunkPreviewComponent implements OnChanges {
    ragId = input.required<number>();
    docId = input.required<number>();
    chunkingState = input.required<DocumentChunkingState>();
    blurredChunk: string = 'The policeman on the beat moved up the avenue impressively. The impressiveness was habitual and not for show, for spectators were few. The time was barely 10 o\'clock at night, but chilly gusts of wind with a taste of rain in them had well nigh depeopled the streets.\n' +
            'Trying doors as he went, twirling his club with many intricate and artful movements, turning now and then to cast his watchful eye adown the pacific thoroughfare, the officer, with his stalwart form and slight swagger, made a fine picture of a guardian of the peace. ';

    private ngZone = inject(NgZone)
    private documentStorageService = inject(NaiveRagDocumentsStorageService);
    private destroyRef = inject(DestroyRef);

    private limit: number = 0;
    private totalChunks: number = 0;
    private bufferLimit: number = 50;
    private nextOffset: number = 0;
    private prevOffset: number = 0;
    loading = signal<boolean>(false);

    chunks = computed<DisplayedChunk[]>(() => {
        const state = this.chunkingState();

        if (state.chunkStrategy !== 'token') {
            return this.calculateChunks(
                state.chunks,
                () => state.chunkOverlap,
                () => state.chunkOverlap
            );
        } else {
            return this.calculateChunks(
                state.chunks,
                (chunk) => chunk.overlap_start_index ?? 0,
                (chunk) => chunk.overlap_end_index ?? 0
            );
        }
    });

    ngOnChanges(changes: SimpleChanges) {
        const state: DocumentChunkingState = this.chunkingState();
        const limit = calcLimit(state.chunkSize);

        this.limit = limit;
        this.totalChunks = state.total;
        this.bufferLimit = limit * 5;

        if (!state.chunks.length) return;

        const firstChunkId = state.chunks[0].chunk_index;
        const lastChunkId = state.chunks[state.chunks.length - 1].chunk_index;

        this.prevOffset = Math.max(firstChunkId - limit - 1, 0);
        this.nextOffset = lastChunkId;
    }

    onScroll(event: Event) {
        if (this.loading()) return;
        const el = event.target as HTMLElement;

        const scrollTop = el.scrollTop;
        const scrollHeight = el.scrollHeight;
        const clientHeight = el.clientHeight;

        const thresholdPx = 500;

        if (scrollTop + clientHeight >= scrollHeight - thresholdPx) {
            this.loadMoreDown(el);
        }

        if (scrollTop <= thresholdPx) {
            this.loadMoreUp(el);
        }
    }

    // Correct scroll position after adding new and removing old items handled in a service
    private loadMoreDown(container: HTMLElement) {
        if (this.loading() || this.nextOffset >= this.totalChunks) return;
        this.loading.set(true);

        this.documentStorageService
            .loadNextChunks(this.ragId(), this.docId(), this.nextOffset, this.limit, this.bufferLimit)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                setTimeout(() => {
                    this.loading.set(false);
                }, 500)
            });
    }

    private loadMoreUp(container: HTMLElement) {
        const firstChunkId = this.chunks()[0]?.chunkIndex;
        if (!firstChunkId || firstChunkId <= 1 || this.loading() || this.prevOffset < 0) return;

        this.loading.set(true);

        const anchorEl = container.querySelector(`[data-chunk-index="${firstChunkId}"]`) as HTMLElement;
        const containerTop = container.getBoundingClientRect().top;
        const anchorRelativeTopBefore = anchorEl?.getBoundingClientRect().top - containerTop || 0;

        this.documentStorageService
            .loadPrevChunks(this.ragId(), this.docId(), this.prevOffset, this.limit, this.bufferLimit)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                this.ngZone.onStable.pipe(take(1)).subscribe(() => {
                    const newAnchorEl = container.querySelector(`[data-chunk-index="${firstChunkId}"]`) as HTMLElement;
                    if (newAnchorEl) {
                        const anchorRelativeTopAfter = newAnchorEl.getBoundingClientRect().top - containerTop;
                        container.scrollTop += anchorRelativeTopAfter - anchorRelativeTopBefore;
                    }
                    this.loading.set(false);
                });
            });
    }

    private calculateChunks(
        chunks: NaiveRagDocumentChunk[],
        getStart: (chunk: NaiveRagDocumentChunk) => number,
        getEnd: (chunk: NaiveRagDocumentChunk) => number
    ): DisplayedChunk[] {
        return chunks.map((chunk, index, arr) => {
            const isFirst = index === 0;
            const isLast = index === arr.length - 1;

            const start = isFirst ? 0 : (getStart(chunk) ?? 0);
            const end = isLast ? 0 : (getEnd(chunk) ?? 0);

            const overlap = isFirst ? '' : chunk.text.slice(0, start);

            const text = end
                ? chunk.text.slice(start, -end)
                : chunk.text.slice(start);

            return {
                chunkIndex: chunk.chunk_index,
                overlap,
                text,
            };
        });
    }
}
