import { NgClass } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    NgZone,
    OnChanges,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MATERIAL_FORMS } from '@shared/material-forms';
import { take } from 'rxjs';

import { ToastService } from '../../../../../services/notifications';
import { calcLimit } from '../../../helpers/calculate-chunks-fetch-limit.util';
import { ChunkSearchState, DocumentChunkingState, NaiveRagDocumentChunk } from '../../../models/naive-rag-chunk.model';
import { ChunkDeepLinkService } from '../../../services/chunk-deep-link.service';
import { ChunkSearchService } from '../../../services/chunk-search.service';
import { NaiveRagDocumentsStorageService } from '../../../services/naive-rag-documents-storage.service';
import { HighlightSegmentsPipe } from './highlight-segments.pipe';

interface TextSegment {
    text: string;
    isMatch: boolean;
    matchIndex: number | null;
}

interface DisplayedChunk {
    chunkIndex: number;
    overlap: string;
    text: string;
    overlapSegments: TextSegment[];
    textSegments: TextSegment[];
}

@Component({
    selector: 'app-chunk-preview',
    templateUrl: './chunk-preview.component.html',
    styleUrls: ['./chunk-preview.component.scss'],
    imports: [NgClass, FormsModule, MATERIAL_FORMS, HighlightSegmentsPipe],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChunkPreviewComponent implements OnChanges, AfterViewInit {
    ragId = input.required<number>();
    docId = input.required<number>();
    collectionId = input.required<number>();
    chunkingState = input.required<DocumentChunkingState>();
    searchState = input<ChunkSearchState | null>(null);
    activeMatchIndex = input<number>(0);

    blurredChunk: string =
        "The policeman on the beat moved up the avenue impressively. The impressiveness was habitual and not for show, for spectators were few. The time was barely 10 o'clock at night, but chilly gusts of wind with a taste of rain in them had well nigh depeopled the streets.\n" +
        'Trying doors as he went, twirling his club with many intricate and artful movements, turning now and then to cast his watchful eye adown the pacific thoroughfare, the officer, with his stalwart form and slight swagger, made a fine picture of a guardian of the peace. ';

    private ngZone = inject(NgZone);
    private documentStorageService = inject(NaiveRagDocumentsStorageService);
    private chunkSearchService = inject(ChunkSearchService);
    private deepLinkService = inject(ChunkDeepLinkService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    private limit: number = 0;
    private totalChunks: number = 0;
    private bufferLimit: number = 50;
    private nextOffset: number = 0;
    private prevOffset: number = 0;
    loading = signal<'up' | 'down' | false>(false);
    chunkHeights = signal<Map<number, number>>(new Map());

    isSearchActive = computed(() => {
        const search = this.searchState();
        return !!search && search.mode !== 'none';
    });

    private isTextSearchWithMore = computed(() => {
        const search = this.searchState();
        return !!search && search.mode === 'text_only' && search.searchHasMore;
    });

    chunks = computed<DisplayedChunk[]>(() => {
        const search = this.searchState();
        const state = this.chunkingState();
        const sourceChunks = this.getSourceChunks(search, state);

        let displayed: DisplayedChunk[];
        if (state.chunkStrategy !== 'token') {
            displayed = this.calculateChunks(
                sourceChunks,
                () => state.chunkOverlap,
                () => state.chunkOverlap
            );
        } else {
            displayed = this.calculateChunks(
                sourceChunks,
                (chunk) => chunk.overlap_start_index ?? 0,
                (chunk) => chunk.overlap_end_index ?? 0
            );
        }

        const query = search?.textQuery ?? '';
        if (query) {
            displayed = this.applyHighlighting(displayed, query);
        }
        return displayed;
    });

    @ViewChild('scrollContainer') private scrollContainer!: ElementRef<HTMLDivElement>;
    @ViewChild('textContainer') private textContainer!: ElementRef<HTMLParagraphElement>;

    constructor() {
        effect(() => {
            this.chunks();
            this.ngZone.onStable.pipe(take(1)).subscribe(() => {
                this.updateChunkHeights();
            });
        });

        effect(() => {
            const matchIdx = this.activeMatchIndex();
            if (matchIdx > 0) {
                this.ngZone.onStable.pipe(take(1)).subscribe(() => {
                    this.scrollToMatch(matchIdx);
                });
            }
        });

        effect(() => {
            const chunks = this.chunks();
            const params = this.deepLinkService.pending();
            if (!params) return;

            const targetChunkId = params.chunkId;
            const hasTarget = chunks.some((c) => c.chunkIndex === targetChunkId);

            if (!hasTarget) {
                if (this.chunkingState().status === 'chunks_ready') {
                    this.toastService.error(`Deep link: chunk ${targetChunkId} not found`);
                    this.deepLinkService.consume();
                    this.deepLinkService.clearUrl();
                }
                return;
            }

            this.ngZone.onStable.pipe(take(1)).subscribe(() => {
                this.scrollToChunk(targetChunkId);
                // Clear pending state with a delay to prevent loading
                // additional chunks during scrolling to targeted chunk
                setTimeout(() => {
                    this.deepLinkService.consume();
                }, 500);
            });
        });
    }

    ngOnChanges() {
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

    ngAfterViewInit() {
        this.checkIfNeedsMoreChunks();

        const resizeObserver = new ResizeObserver(() => {
            this.ngZone.run(() => this.updateChunkHeights());
        });
        resizeObserver.observe(this.scrollContainer.nativeElement);

        this.destroyRef.onDestroy(() => resizeObserver.disconnect());
    }

    onChunkIdClick(chunkIndex: number): void {
        const url = this.deepLinkService.buildUrl(this.collectionId(), this.ragId(), this.docId(), chunkIndex);
        void navigator.clipboard.writeText(url);
        this.deepLinkService.updateUrl(this.collectionId(), this.ragId(), this.docId(), chunkIndex);
    }

    onScroll(event: Event) {
        if (this.loading() || this.deepLinkService.pending()) return;
        const el = event.target as HTMLElement;
        const scrollTop = el.scrollTop;
        const scrollHeight = el.scrollHeight;
        const clientHeight = el.clientHeight;
        const thresholdPx = 500;

        if (this.isTextSearchWithMore()) {
            if (scrollTop + clientHeight >= scrollHeight - thresholdPx) {
                this.loadMoreSearchDown();
            }
            return;
        }

        if (this.isSearchActive()) return;

        if (scrollTop + clientHeight >= scrollHeight - thresholdPx) {
            this.loadMoreDown(el);
        }

        if (scrollTop <= thresholdPx) {
            this.loadMoreUp(el);
        }
    }

    private updateChunkHeights(): void {
        const textEl = this.textContainer?.nativeElement;
        if (!textEl) return;

        const chunkEls = Array.from(textEl.querySelectorAll<HTMLElement>('[data-chunk-index]'));
        if (!chunkEls.length) return;

        const heights = new Map<number, number>();
        chunkEls.forEach((el, i) => {
            const chunkIndex = Number(el.dataset['chunkIndex']);
            const elTop = el.getBoundingClientRect().top - textEl.getBoundingClientRect().top;
            const nextEl = chunkEls[i + 1];
            const nextTop = nextEl ? nextEl.getBoundingClientRect().top - textEl.getBoundingClientRect().top : 20;
            heights.set(chunkIndex, Math.max(nextTop - elTop, 0));
        });

        this.chunkHeights.set(heights);
    }

    private loadMoreDown(container: HTMLElement) {
        if (this.loading() || this.nextOffset >= this.totalChunks) return;
        this.loading.set('down');

        // Capture anchor: first chunk element before any DOM change
        const firstChunkIndex = this.chunks()[0]?.chunkIndex;
        const anchorEl =
            firstChunkIndex != null
                ? (container.querySelector(`[data-chunk-index="${firstChunkIndex}"]`) as HTMLElement | null)
                : null;
        const containerTop = container.getBoundingClientRect().top;
        const anchorRelativeTopBefore = anchorEl ? anchorEl.getBoundingClientRect().top - containerTop : null;

        this.documentStorageService
            .loadNextChunks(this.ragId(), this.docId(), this.nextOffset, this.limit, this.bufferLimit)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                this.ngZone.onStable.pipe(take(1)).subscribe(() => {
                    // If the anchor element was removed (top trim), compensate scroll
                    if (anchorEl && anchorRelativeTopBefore !== null) {
                        const anchorRelativeTopAfter = anchorEl.isConnected
                            ? anchorEl.getBoundingClientRect().top - containerTop
                            : null;
                        if (anchorRelativeTopAfter !== null) {
                            container.scrollTop += anchorRelativeTopAfter - anchorRelativeTopBefore;
                        }
                    }
                    this.loading.set(false);
                    this.checkIfNeedsMoreChunks();
                });
            });
    }

    private loadMoreUp(container: HTMLElement) {
        const firstChunkId = this.chunks()[0]?.chunkIndex;
        if (!firstChunkId || firstChunkId <= 1 || this.loading() || this.prevOffset < 0) return;

        this.loading.set('up');

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

            const text = end ? chunk.text.slice(start, -end) : chunk.text.slice(start);

            return {
                chunkIndex: chunk.chunk_index,
                overlap,
                text,
                overlapSegments: [{ text: overlap, isMatch: false, matchIndex: null }],
                textSegments: [{ text, isMatch: false, matchIndex: null }],
            };
        });
    }

    private getSourceChunks(search: ChunkSearchState | null, state: DocumentChunkingState): NaiveRagDocumentChunk[] {
        if (!search || search.mode === 'none') return state.chunks;
        if (search.mode === 'id_only' || search.mode === 'id_and_text') return search.searchedChunks;
        if (search.mode === 'text_only') return search.searchedChunks;
        return state.chunks;
    }

    private applyHighlighting(chunks: DisplayedChunk[], query: string): DisplayedChunk[] {
        const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escaped})`, 'gi');
        let globalMatchIndex = 0;

        return chunks.map((chunk) => ({
            ...chunk,
            overlapSegments: this.splitByQuery(
                chunk.overlap,
                regex,
                (idx) => {
                    globalMatchIndex = idx;
                    return idx;
                },
                globalMatchIndex
            ),
            textSegments: this.splitByQuery(
                chunk.text,
                regex,
                (idx) => {
                    globalMatchIndex = idx;
                    return idx;
                },
                globalMatchIndex
            ),
        }));
    }

    private splitByQuery(
        text: string,
        regex: RegExp,
        trackIndex: (idx: number) => number,
        startIndex: number
    ): TextSegment[] {
        if (!text) return [{ text: '', isMatch: false, matchIndex: null }];

        const segments: TextSegment[] = [];
        let lastIndex = 0;
        let currentMatchIndex = startIndex;
        let match: RegExpExecArray | null;

        regex.lastIndex = 0;
        while ((match = regex.exec(text)) !== null) {
            if (match.index > lastIndex) {
                segments.push({ text: text.slice(lastIndex, match.index), isMatch: false, matchIndex: null });
            }
            currentMatchIndex++;
            segments.push({ text: match[0], isMatch: true, matchIndex: currentMatchIndex });
            lastIndex = regex.lastIndex;
        }

        if (lastIndex < text.length) {
            segments.push({ text: text.slice(lastIndex), isMatch: false, matchIndex: null });
        }

        trackIndex(currentMatchIndex);

        if (!segments.length) {
            segments.push({ text, isMatch: false, matchIndex: null });
        }

        return segments;
    }

    private loadMoreSearchDown(): void {
        if (this.loading()) return;
        this.loading.set('down');

        this.chunkSearchService
            .loadMoreSearchResults(this.ragId(), this.docId())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                this.loading.set(false);
            });
    }

    private scrollToChunk(chunkIndex: number): void {
        this.scrollToElement(`[data-chunk-index="${chunkIndex}"]`);
    }

    private scrollToMatch(matchIndex: number): void {
        this.scrollToElement(`[data-match-index="${matchIndex}"]`);
    }

    private scrollToElement(selector: string): void {
        const container = this.scrollContainer?.nativeElement;

        if (!container) return;

        const element = container.querySelector<HTMLElement>(selector);

        element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    private checkIfNeedsMoreChunks(): void {
        const el = this.scrollContainer?.nativeElement;
        if (!el || this.loading()) return;

        const hasScroll = el.scrollHeight > el.clientHeight;
        if (hasScroll) return;

        if (this.isTextSearchWithMore()) {
            this.loadMoreSearchDown();
        } else if (!this.isSearchActive() && this.nextOffset < this.totalChunks) {
            this.loadMoreDown(el);
        }
    }
}
