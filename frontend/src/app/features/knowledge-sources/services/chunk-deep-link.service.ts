import { inject, Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';

export interface ChunkDeepLinkParams {
    collectionId: number;
    ragId: number;
    documentId: number;
    chunkId: number;
}

@Injectable({
    providedIn: 'root',
})
export class ChunkDeepLinkService {
    private router = inject(Router);

    private readonly pagePath = '/storage/knowledge-sources';

    pending = signal<ChunkDeepLinkParams | null>(null);

    /**
     * Parse deep-link params from the current URL query string.
     * Returns the params if all required fields are present, otherwise null.
     */
    parseFromCurrentUrl(): ChunkDeepLinkParams | null {
        const url = new URL(window.location.href);
        const collection = url.searchParams.get('collection');
        const rag = url.searchParams.get('rag');
        const doc = url.searchParams.get('doc');
        const chunk = url.searchParams.get('chunk');

        if (!collection || !rag || !doc || !chunk) return null;

        const params: ChunkDeepLinkParams = {
            collectionId: +collection,
            ragId: +rag,
            documentId: +doc,
            chunkId: +chunk,
        };

        if (Object.values(params).some((v) => isNaN(v) || v <= 0)) return null;

        return params;
    }

    /**
     * Set pending deep-link from current URL. Called once on page init.
     */
    initFromUrl(): void {
        const params = this.parseFromCurrentUrl();
        if (params) {
            this.pending.set(params);
        }
    }

    /**
     * Consume and clear the pending deep-link params.
     */
    consume(): ChunkDeepLinkParams | null {
        const params = this.pending();
        this.pending.set(null);
        return params;
    }

    /**
     * Update the browser URL with chunk deep-link params (no page reload).
     */
    updateUrl(collectionId: number, ragId: number, documentId: number, chunkId: number): void {
        void this.router.navigate([], {
            queryParams: { collection: collectionId, rag: ragId, doc: documentId, chunk: chunkId },
        });
    }

    /**
     * Clear deep-link query params from URL.
     */
    clearUrl(): void {
        void this.router.navigate([], {
            queryParams: {},
        });
    }

    /**
     * Build a shareable URL string for a specific chunk.
     */
    buildUrl(collectionId: number, ragId: number, documentId: number, chunkId: number): string {
        const base = window.location.origin + this.pagePath;
        return `${base}?collection=${collectionId}&rag=${ragId}&doc=${documentId}&chunk=${chunkId}`;
    }
}
