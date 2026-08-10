import { inject, Injectable, signal } from '@angular/core';
import { isEqual } from 'lodash-es';
import { EMPTY, Observable, throwError } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';

import { TableDocument } from '../components/naive-rag-configuration/configuration-table/configuration-table.interface';
import { calcLimit } from '../helpers/calculate-chunks-fetch-limit.util';
import {
    CancelNaiveNaiveRagChunkingResponse,
    ChunkedWithParams,
    DocumentChunkingState,
    GetNaiveRagDocumentChunksResponse,
    NaiveRagChunkingResponse,
    NaiveRagDocumentChunk,
} from '../models/naive-rag-chunk.model';
import { RunNaiveRagDocumentChunkingRequest } from '../models/naive-rag-document.model';
import { NaiveRagService } from './naive-rag.service';

/**
 * Owns the per-document chunk-preview state (`DocumentChunkingState`) and the
 * chunk-related HTTP operations (fetch preview, pagination, run/stop chunking).
 */
@Injectable({
    providedIn: 'root',
})
export class NaiveRagChunkPreviewService {
    private readonly naiveRagService = inject(NaiveRagService);

    private documentStatesSignal = signal<Map<number, DocumentChunkingState>>(new Map());
    public documentStates = this.documentStatesSignal.asReadonly();

    public initDocumentStatesMap(documents: TableDocument[]): void {
        const docStateMap = new Map<number, DocumentChunkingState>();
        documents.forEach((doc) => {
            docStateMap.set(doc.naive_rag_document_id, this.createDocumentState(doc));
        });
        this.documentStatesSignal.set(docStateMap);
    }

    /**
     * Called from polling merges. Keeps state entries for docs still present
     * on the server and creates fresh entries for newly-arriving docs.
     */
    public syncStatesWithDocs(documents: TableDocument[]): void {
        this.documentStatesSignal.update((states) => {
            const next = new Map<number, DocumentChunkingState>();
            for (const doc of documents) {
                next.set(
                    doc.naive_rag_document_id,
                    states.get(doc.naive_rag_document_id) ?? this.createDocumentState(doc)
                );
            }
            return next;
        });
    }

    public removeDocsFromState(ragDocIds: number[]): void {
        if (!ragDocIds.length) return;

        this.documentStatesSignal.update((prevMap) => {
            const newMap = new Map(prevMap);
            for (const id of ragDocIds) {
                newMap.delete(id);
            }
            return newMap;
        });
    }

    public clear(): void {
        this.documentStatesSignal.set(new Map());
    }

    public reconcileStatus(documentId: number, effectiveParams: ChunkedWithParams): void {
        this.updateDocState(documentId, (s) => {
            if (!s.chunkedWith) return s;
            if (s.status === 'chunking' || s.status === 'fetching_chunks') return s;

            const paramsMatch = isEqual(s.chunkedWith, effectiveParams);
            if (paramsMatch) {
                if (s.status !== 'chunks_outdated') return s;
                return s.chunks.length > 0 ? { ...s, status: 'chunks_ready' } : { ...s, status: 'new' };
            }

            return s.status === 'chunks_outdated' ? s : { ...s, status: 'chunks_outdated' };
        });
    }

    // ================= CHUNK PREVIEW =================

    /**
     * `docParams` (optional) refreshes `chunkStrategy` / `chunkOverlap` on the
     * state entry after a successful fetch. Callers that have access to the
     * current effective doc (via the storage service) pass it so the chunk
     * preview UI reflects freshly-applied edits.
     */
    public fetchChunks(
        naiveRagId: number,
        documentId: number,
        startOffset: number = 0,
        docParams?: { chunkStrategy: DocumentChunkingState['chunkStrategy']; chunkOverlap: number }
    ): Observable<GetNaiveRagDocumentChunksResponse> {
        this.updateDocState(documentId, (s) => ({ ...s, status: 'fetching_chunks' }));

        const docChunkSize = this.documentStates().get(documentId)?.chunkSize;
        const limit = docChunkSize ? calcLimit(docChunkSize) : 50;
        const offset = Math.max(startOffset - Math.floor(limit / 2), 0);

        return this.naiveRagService.getChunkPreview(naiveRagId, documentId, offset, limit).pipe(
            tap(({ chunks, total_chunks }) => {
                const state = this.documentStates().get(documentId);
                // document was updated during fetching
                if (state?.status === 'chunks_outdated') return;
                if (!state) return;

                this.updateDocState(documentId, (s) => ({
                    ...s,
                    status: 'chunks_ready',
                    chunkStrategy: docParams?.chunkStrategy ?? s.chunkStrategy,
                    chunkOverlap: docParams?.chunkOverlap ?? s.chunkOverlap,
                    chunkSize: this.calcAvgChunkSize(chunks),
                    total: total_chunks,
                    chunks,
                }));
            }),
            catchError((err) => throwError(() => err))
        );
    }

    public loadNextChunks(
        naiveRagId: number,
        documentId: number,
        offset: number,
        limit: number,
        bufferLimit: number
    ): Observable<{ removedCount: number; fetchedCount: number }> {
        return this.naiveRagService.getChunkPreview(naiveRagId, documentId, offset, limit).pipe(
            map(({ chunks }) => {
                let removedCount: number = 0;
                // Update doc state in two steps prevents breaking scroll position
                this.updateDocState(documentId, (s) => {
                    const existingIndices = new Set(s.chunks.map((c) => c.chunk_index));
                    const newChunks = chunks.filter((c) => !existingIndices.has(c.chunk_index));
                    const merged = [...s.chunks, ...newChunks];
                    return {
                        ...s,
                        removedCount,
                        chunkSize: this.calcAvgChunkSize(merged),
                        chunks: merged,
                    };
                });
                setTimeout(() => {
                    this.updateDocState(documentId, (s) => {
                        const updatedChunks = s.chunks;
                        if (updatedChunks.length > bufferLimit) {
                            removedCount = updatedChunks.length - bufferLimit;
                            updatedChunks.splice(0, removedCount);
                        }
                        return { ...s, removedCount, chunks: updatedChunks };
                    });
                }, 100);

                return { removedCount, fetchedCount: chunks.length };
            }),
            catchError((err) => throwError(() => err))
        );
    }

    public loadPrevChunks(
        naiveRagId: number,
        documentId: number,
        offset: number,
        limit: number,
        bufferLimit: number
    ): Observable<{ removedCount: number; fetchedCount: number }> {
        return this.naiveRagService.getChunkPreview(naiveRagId, documentId, offset, limit).pipe(
            map(({ chunks }) => {
                let removedCount: number = 0;
                this.updateDocState(documentId, (s) => {
                    const existingIndices = new Set(s.chunks.map((c) => c.chunk_index));
                    const newChunks = chunks.filter((c) => !existingIndices.has(c.chunk_index));
                    let updatedChunks = [...newChunks, ...s.chunks];
                    if (updatedChunks.length > bufferLimit) {
                        removedCount = updatedChunks.length - bufferLimit;
                        updatedChunks.splice(updatedChunks.length - removedCount, removedCount);
                    }
                    return {
                        ...s,
                        removedCount,
                        chunkSize: this.calcAvgChunkSize(updatedChunks),
                        chunks: updatedChunks,
                    };
                });
                return { removedCount, fetchedCount: chunks.length };
            }),
            catchError((err) => throwError(() => err))
        );
    }

    public stopChunking(
        ragId: number,
        documentId: number,
        body: RunNaiveRagDocumentChunkingRequest
    ): Observable<CancelNaiveNaiveRagChunkingResponse> {
        this.updateDocState(documentId, (s) => ({ ...s, status: 'new' }));
        return this.naiveRagService.stopChunkingByDocumentId(ragId, documentId, body);
    }

    public runChunking(
        ragId: number,
        documentId: number,
        body: RunNaiveRagDocumentChunkingRequest
    ): Observable<NaiveRagChunkingResponse> {
        const initialState = this.documentStates().get(documentId);
        if (!initialState) return EMPTY;

        this.updateDocState(documentId, (s) => ({ ...s, status: 'chunking' }));

        return this.naiveRagService.runChunkingProcess(ragId, documentId, body).pipe(
            tap((res) => {
                const state = this.documentStates().get(documentId);
                if (state?.status === 'chunks_outdated') return;

                switch (res.status) {
                    case 'completed': {
                        this.updateDocState(documentId, (s) => ({
                            ...s,
                            status: 'chunked',
                            chunkedWith: this.snapshotChunkedWith(body),
                        }));
                        return;
                    }
                    case 'cancelled': {
                        return;
                    }
                    case 'failed': {
                        this.updateDocState(documentId, (s) => ({ ...s, status: 'chunking_failed' }));
                        return;
                    }
                    case 'timeout': {
                        this.updateDocState(documentId, (s) => ({ ...s, status: 'chunking_timeout' }));
                        return;
                    }
                }
            }),
            catchError((err) => {
                this.updateDocState(documentId, (s) =>
                    s.status === 'chunking' ? { ...s, status: initialState.status } : s
                );
                return throwError(() => err);
            })
        );
    }

    private updateDocState(ragDocId: number, updater: (state: DocumentChunkingState) => DocumentChunkingState): void {
        this.documentStatesSignal.update((prevMap) => {
            const prevState = prevMap.get(ragDocId);
            if (!prevState) return prevMap;

            const nextMap = new Map(prevMap);
            const nextState = updater(prevState);
            if (nextState === prevState) return prevMap;
            nextMap.set(ragDocId, nextState);
            return nextMap;
        });
    }

    private createDocumentState(doc: TableDocument): DocumentChunkingState {
        return {
            id: doc.naive_rag_document_id,
            status: this.deriveInitialStatus(doc),

            chunkedWith: doc.status === 'completed' ? this.snapshotChunkedWithFromDoc(doc) : undefined,
            chunkOverlap: doc.chunk_overlap,
            chunkSize: doc.chunk_size,
            chunkStrategy: doc.chunk_strategy,
            total: 0,
            removedCount: 0,
            chunks: [],
        };
    }

    private deriveInitialStatus(doc: TableDocument): DocumentChunkingState['status'] {
        switch (doc.status) {
            case 'new':
            case 'processing':
            case 'outdated':
            case 'completed':
                return 'new';
            default:
                return 'chunking_failed';
        }
    }

    private snapshotChunkedWith(body: RunNaiveRagDocumentChunkingRequest): ChunkedWithParams {
        return {
            chunk_strategy: body.chunk_strategy,
            chunk_size: body.chunk_size,
            chunk_overlap: body.chunk_overlap,
            additional_params: (body.additional_params ?? {}) as ChunkedWithParams['additional_params'],
        };
    }

    private snapshotChunkedWithFromDoc(doc: TableDocument): ChunkedWithParams {
        return {
            chunk_strategy: doc.chunk_strategy,
            chunk_size: doc.chunk_size,
            chunk_overlap: doc.chunk_overlap,
            additional_params: doc.additional_params,
        };
    }

    private calcAvgChunkSize(chunks: NaiveRagDocumentChunk[]): number {
        return chunks.reduce((sum, item) => sum + item.text.length, 0) / chunks.length;
    }
}
