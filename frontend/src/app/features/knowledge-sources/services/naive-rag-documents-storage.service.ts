import { computed, inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { isEqual } from 'lodash-es';
import { EMPTY, Observable, throwError } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';

import {
    NormalizedDocumentErrors,
    TableDocument,
} from '../components/naive-rag-configuration/configuration-table/configuration-table.interface';
import { calcLimit } from '../helpers/calculate-chunks-fetch-limit.util';
import { normalizeBulkUpdateErrors } from '../helpers/normalize-bulk-update-errors.util';
import { transformToTableDocuments } from '../helpers/transform-to-table-document.util';
import {
    CancelNaiveNaiveRagChunkingResponse,
    DocumentChunkingState,
    DocumentChunksStatus,
    GetNaiveRagDocumentChunksResponse,
    NaiveRagChunkingResponse,
    NaiveRagDocumentChunk,
} from '../models/naive-rag-chunk.model';
import {
    BulkDeleteNaiveRagDocumentDtoResponse,
    BulkUpdateNaiveRagDocumentsRequest,
    BulkUpdateNaiveRagDocumentsResponse,
    NaiveRagDocumentConfig,
    RunNaiveRagDocumentChunkingRequest,
    UpdateNaiveRagDocumentDtoRequest,
} from '../models/naive-rag-document.model';
import { NaiveRagService } from './naive-rag.service';

type PendingField = keyof UpdateNaiveRagDocumentDtoRequest;

@Injectable({
    providedIn: 'root',
})
//TODO check is refactoring needed and divide into separate services
export class NaiveRagDocumentsStorageService implements StorageService {
    private savedDocsSignal = signal<TableDocument[]>([]);

    private pendingSignal = signal<Map<number, UpdateNaiveRagDocumentDtoRequest>>(new Map());
    public pending = this.pendingSignal.asReadonly();

    public documents = computed<TableDocument[]>(() => {
        const pending = this.pendingSignal();
        return this.savedDocsSignal().map((d) => {
            const patch = pending.get(d.naive_rag_document_id);
            if (!patch) return d;
            return { ...d, ...patch } as TableDocument;
        });
    });

    // Set of document IDs that currently have any pending fields — used by UI to show rollback.
    public pendingDocIds = computed<Set<number>>(() => new Set(this.pendingSignal().keys()));

    private documentStatesSignal = signal<Map<number, DocumentChunkingState>>(new Map());
    public documentStates = this.documentStatesSignal.asReadonly();

    private readonly naiveRagService = inject(NaiveRagService);

    public fetchDocumentConfigs(naiveRagId: number): Observable<TableDocument[]> {
        return this.naiveRagService.getDocumentConfigs(naiveRagId).pipe(
            map(({ configs }) => transformToTableDocuments(configs)),
            tap((documents) => this.initDocumentStatesMap(documents)),
            tap((documents) => this.savedDocsSignal.set(documents)),
            catchError((err) => throwError(() => err))
        );
    }

    public fetchChunks(
        naiveRagId: number,
        documentId: number,
        startOffset: number = 0
    ): Observable<GetNaiveRagDocumentChunksResponse> {
        this.updateDocState(documentId, (s) => ({ ...s, status: 'fetching_chunks' }));

        const docChunkSize = this.documents().find((d) => d.naive_rag_document_id === documentId)?.chunk_size;
        const limit = docChunkSize ? calcLimit(docChunkSize) : 50;
        const offset = Math.max(startOffset - Math.floor(limit / 2), 0);

        return this.naiveRagService.getChunkPreview(naiveRagId, documentId, offset, limit).pipe(
            tap(({ chunks, total_chunks }) => {
                const state = this.documentStates().get(documentId);
                // document was updated during fetching
                if (state?.status === 'chunks_outdated') return;

                const docData = this.documents().find((d) => d.naive_rag_document_id === documentId);
                if (!docData) return;

                this.updateDocState(documentId, (s) => ({
                    ...s,
                    status: 'chunks_ready',
                    chunkStrategy: docData.chunk_strategy,
                    chunkOverlap: docData.chunk_overlap,
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

    private calcAvgChunkSize(chunks: NaiveRagDocumentChunk[]): number {
        return chunks.reduce((sum, item) => sum + item.text.length, 0) / chunks.length;
    }

    public initDocumentStatesMap(documents: TableDocument[]): void {
        const docStateMap = new Map<number, DocumentChunkingState>();
        documents.forEach((doc) => {
            docStateMap.set(doc.naive_rag_document_id, this.createDocumentState(doc));
        });
        this.documentStatesSignal.set(docStateMap);
    }

    private createDocumentState(doc: TableDocument): DocumentChunkingState {
        let status: DocumentChunksStatus;

        switch (doc.status) {
            case 'new':
            case 'processing':
            case 'outdated':
            case 'completed': // document-config status 'completed' does not represent is chunks up-to-date
                status = 'new';
                break;
            default:
                status = 'chunking_failed';
        }

        return {
            id: doc.naive_rag_document_id,
            status: status,
            chunkOverlap: doc.chunk_overlap,
            chunkSize: doc.chunk_size,
            chunkStrategy: doc.chunk_strategy,
            total: 0,
            removedCount: 0,
            chunks: [],
        };
    }

    stopChunking(ragId: number, documentId: number): Observable<CancelNaiveNaiveRagChunkingResponse> {
        this.updateDocState(documentId, (s) => ({ ...s, status: 'new' }));
        return this.naiveRagService.stopChunkingByDocumentId(ragId, documentId);
    }

    runChunking(ragId: number, documentId: number): Observable<NaiveRagChunkingResponse> {
        const initialState = this.documentStates().get(documentId);
        if (!initialState) return EMPTY;

        this.updateDocState(documentId, (s) => ({ ...s, status: 'chunking' }));

        const body = this.buildFullParamsBody(documentId);
        if (!body) return EMPTY;

        return this.naiveRagService.runChunkingProcess(ragId, documentId, body).pipe(
            tap((res) => {
                const state = this.documentStates().get(documentId);
                if (state?.status === 'chunks_outdated') return;

                switch (res.status) {
                    case 'completed': {
                        this.updateDocState(documentId, (s) => ({ ...s, status: 'chunked' }));
                        return;
                    }
                    case 'canceled': {
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
            catchError(() => {
                this.updateDocState(documentId, (s) => ({ ...s, status: 'chunking_failed' }));
                return EMPTY;
            })
        );
    }

    private buildFullParamsBody(documentId: number): RunNaiveRagDocumentChunkingRequest | undefined {
        const doc = this.documents().find((d) => d.naive_rag_document_id === documentId);
        if (!doc) return;
        return {
            chunk_strategy: doc.chunk_strategy,
            chunk_size: doc.chunk_size,
            chunk_overlap: doc.chunk_overlap,
            additional_params: doc.additional_params,
        };
    }

    /**
     * Sets a single pending field. If value equals saved, removes the field from pending
     * (and drops the entry entirely if it becomes empty).
     */
    public setPendingField(documentId: number, field: PendingField, value: string | number | null): void {
        if (value === null) return;

        const saved = this.savedDocsSignal().find((d) => d.naive_rag_document_id === documentId);
        if (!saved) return;

        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            const current = { ...(next.get(documentId) ?? {}) };
            const savedValue = saved[field];

            if (savedValue === value) {
                delete (current as Record<string, unknown>)[field];
            } else {
                (current as Record<string, unknown>)[field] = value;
            }

            if (Object.keys(current).length === 0) {
                next.delete(documentId);
                this.restoreOutdatedStatus(documentId);
            } else {
                next.set(documentId, current);
                this.flipToOutdatedStatus(documentId);
            }
            return next;
        });
    }

    /**
     * Sets multiple pending fields at once (used from tune modal, and by bulk-row apply).
     * Fields equal to baseline are stripped; empty resulting entries are removed.
     */
    public setPendingFields(documentId: number, patch: UpdateNaiveRagDocumentDtoRequest): void {
        const baseline = this.savedDocsSignal().find((d) => d.naive_rag_document_id === documentId);
        if (!baseline) return;

        const baselineAsRecord = baseline as unknown as Record<string, unknown>;

        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            const current: Record<string, unknown> = { ...(next.get(documentId) ?? {}) };

            for (const [key, value] of Object.entries(patch)) {
                if (value === undefined || value === null) continue;

                const baselineValue = baselineAsRecord[key];
                if (isEqual(baselineValue, value)) {
                    delete current[key];
                } else {
                    current[key] = value;
                }
            }

            if (Object.keys(current).length === 0) {
                next.delete(documentId);
                this.restoreOutdatedStatus(documentId);
            } else {
                next.set(documentId, current);
                this.flipToOutdatedStatus(documentId);
            }
            return next;
        });
    }

    public clearPending(documentIds: number[]): void {
        if (!documentIds.length) return;

        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            for (const id of documentIds) {
                next.delete(id);
            }
            return next;
        });

        this.savedDocsSignal.update((items) =>
            items.map((item) => {
                if (!documentIds.includes(item.naive_rag_document_id)) return item;
                return { ...item, checked: false, errors: item.errors ? {} : item.errors };
            })
        );

        for (const id of documentIds) {
            this.restoreOutdatedStatus(id);
        }
    }

    private flipToOutdatedStatus(documentId: number): void {
        this.updateDocState(documentId, (s) => {
            if (s.status === 'new') return s;
            if (s.status === 'chunks_outdated') return s;
            return { ...s, status: 'chunks_outdated', preOutdatedStatus: s.status };
        });
    }

    private restoreOutdatedStatus(documentId: number): void {
        this.updateDocState(documentId, (s) => {
            if (s.status !== 'chunks_outdated' || !s.preOutdatedStatus) return s;
            const { preOutdatedStatus, ...rest } = s;
            return { ...rest, status: preOutdatedStatus };
        });
    }

    // ================= BULK SAVE + INDEXING SUPPORT =================
    public bulkPartialUpdate(ragId: number, docIds: number[]): Observable<BulkUpdateNaiveRagDocumentsResponse> {
        if (!docIds.length) return EMPTY;

        const pendingMap = this.pendingSignal();
        const effective = this.documents();
        const configs: BulkUpdateNaiveRagDocumentsRequest[] = [];
        for (const id of docIds) {
            if (!pendingMap.has(id)) continue;
            const doc = effective.find((d) => d.naive_rag_document_id === id);
            if (!doc) continue;
            configs.push({
                id: id,
                chunk_strategy: doc.chunk_strategy,
                chunk_size: doc.chunk_size,
                chunk_overlap: doc.chunk_overlap,
                additional_params: doc.additional_params,
            });
        }

        if (!configs.length) return EMPTY;

        return this.naiveRagService.bulkUpdateDocumentConfigs(ragId, configs).pipe(
            tap((response) => this.handleBulkPartialUpdate(response)),
            catchError((err) => throwError(() => err))
        );
    }

    // ================= TABLE UTILITIES =================

    public toggleAll(all: boolean, ids?: number[]) {
        const idSet = ids ? new Set(ids) : null;
        this.savedDocsSignal.update((items) =>
            items.map((i) => {
                if (idSet && !idSet.has(i.naive_rag_document_id)) return i;
                return { ...i, checked: !all };
            })
        );
    }

    public toggleDocument(id: number) {
        this.savedDocsSignal.update((items) =>
            items.map((i) => {
                return i.naive_rag_document_id === id ? { ...i, checked: !i.checked } : i;
            })
        );
    }

    /**
     * Called by polling. Merges server-side config into baseline without touching
     * pending overrides. Pending entries for documents that disappeared from the
     * server response are pruned.
     */
    public updateDocumentsFromConfigs(configs: NaiveRagDocumentConfig[]): void {
        const itemMap = new Map(this.savedDocsSignal().map((d) => [d.naive_rag_document_id, d]));

        const documents = configs.map((config) => {
            const item = itemMap.get(config.naive_rag_document_id);
            return item ? { ...item, ...config } : { ...config, checked: false };
        });
        this.savedDocsSignal.set(documents);

        const presentIds = new Set(documents.map((d) => d.naive_rag_document_id));
        this.pendingSignal.update((prev) => {
            let mutated = false;
            const next = new Map(prev);
            for (const id of prev.keys()) {
                if (!presentIds.has(id)) {
                    next.delete(id);
                    mutated = true;
                }
            }
            return mutated ? next : prev;
        });

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

    public bulkDeleteDocConfigs(
        ragId: number,
        config_ids: number[]
    ): Observable<BulkDeleteNaiveRagDocumentDtoResponse> {
        if (!config_ids.length) return EMPTY;

        return this.naiveRagService.bulkDeleteDocumentConfigs(ragId, { config_ids }).pipe(
            tap((response) => this.handleSuccessBulkDelete(response)),
            catchError((err) => throwError(() => err))
        );
    }

    private updateDocState(ragDocId: number, updater: (state: DocumentChunkingState) => DocumentChunkingState): void {
        this.documentStatesSignal.update((prevMap) => {
            const prevState = prevMap.get(ragDocId);
            if (!prevState) {
                return prevMap;
            }

            const nextMap = new Map(prevMap);
            const nextState = updater(prevState);

            nextMap.set(ragDocId, nextState);
            return nextMap;
        });
    }

    private removeDocsFromState(ragDocIds: number[]): void {
        if (!ragDocIds.length) return;

        this.documentStatesSignal.update((prevMap) => {
            const newMap = new Map(prevMap);

            for (const id of ragDocIds) {
                newMap.delete(id);
            }

            return newMap;
        });
    }

    // ================= HANDLERS =================

    private handleBulkPartialUpdate(res: BulkUpdateNaiveRagDocumentsResponse): void {
        const configMap = new Map(res.configs.map((c) => [c.naive_rag_document_id, c]));

        this.savedDocsSignal.update((items) =>
            items.map((item) => {
                const updated = configMap.get(item.naive_rag_document_id);
                if (!updated) return item;
                const normalizedErrors: NormalizedDocumentErrors = normalizeBulkUpdateErrors(updated.errors);
                return {
                    ...item,
                    ...updated,
                    errors: normalizedErrors,
                };
            })
        );

        // Clear pending only for docs that came back without per-field errors.
        // Docs with errors keep their pending values so the user can fix and retry.
        const clearedIds: number[] = [];
        for (const [id, updated] of configMap) {
            if (!updated.errors || updated.errors.length === 0) {
                clearedIds.push(id);
            }
        }
        if (clearedIds.length) {
            this.pendingSignal.update((prev) => {
                const next = new Map(prev);
                for (const id of clearedIds) {
                    next.delete(id);
                }
                return next;
            });
            // Also uncheck saved rows so the disabled-checkbox rule stays consistent.
            this.savedDocsSignal.update((items) =>
                items.map((i) => (clearedIds.includes(i.naive_rag_document_id) ? { ...i, checked: false } : i))
            );
        }

        this.documentStatesSignal.update((prevMap) => {
            const nextMap = new Map(prevMap);

            for (const [docId, updated] of configMap) {
                const prevState = nextMap.get(docId);
                if (!prevState) continue;

                nextMap.set(docId, {
                    ...prevState,
                    status: prevState.status !== 'new' ? 'chunks_outdated' : prevState.status,
                    chunkStrategy: updated.chunk_strategy,
                    chunkSize: updated.chunk_size,
                    // Update overlap only after chunk fetching
                    // chunkOverlap: updated.chunk_overlap,
                    total: updated.total_chunks,
                });
            }

            return nextMap;
        });
    }

    clear(): void {
        this.savedDocsSignal.set([]);
        this.pendingSignal.set(new Map());
        this.documentStatesSignal.set(new Map());
    }

    private handleSuccessBulkDelete(res: BulkDeleteNaiveRagDocumentDtoResponse) {
        const deletedIds = res.deleted_config_ids;
        this.savedDocsSignal.update((items) =>
            items.filter((i) => {
                return !deletedIds.includes(i.naive_rag_document_id);
            })
        );
        this.pendingSignal.update((prev) => {
            const next = new Map(prev);
            for (const id of deletedIds) {
                next.delete(id);
            }
            return next;
        });
        this.removeDocsFromState(deletedIds);
    }
}
