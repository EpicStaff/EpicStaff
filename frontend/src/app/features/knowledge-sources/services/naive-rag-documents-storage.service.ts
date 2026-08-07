import { computed, inject, Injectable } from '@angular/core';
import { StorageService } from '@shared/services';
import { EMPTY, Observable, throwError } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';

import { TableDocument } from '../components/naive-rag-configuration/configuration-table/configuration-table.interface';
import {
    CancelNaiveNaiveRagChunkingResponse,
    ChunkedWithParams,
    GetNaiveRagDocumentChunksResponse,
    NaiveRagChunkingResponse,
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
import { NaiveRagChunkPreviewService } from './naive-rag-chunk-preview.service';
import { NaiveRagDocumentsCatalogService } from './naive-rag-documents-catalog.service';
import { NaiveRagPendingDeletesService } from './naive-rag-pending-deletes.service';
import { NaiveRagPendingEditsService } from './naive-rag-pending-edits.service';

type PendingField = keyof UpdateNaiveRagDocumentDtoRequest;

/**
 * Facade that composes the four naive-rag document sub-services and
 * exposes an aggregated view + a small set of cross-cutting HTTP flows.
 *
 * Sub-services (each with a single axis of state):
 *   - `NaiveRagDocumentsCatalogService` — baseline docs from server.
 *   - `NaiveRagPendingEditsService` — per-doc pending field edits.
 *   - `NaiveRagPendingDeletesService` — soft-delete set + delete HTTP.
 *   - `NaiveRagChunkPreviewService` — chunk preview state + chunk HTTP.
 */
@Injectable({
    providedIn: 'root',
})
export class NaiveRagDocumentsStorageService implements StorageService {
    private readonly naiveRagService = inject(NaiveRagService);
    private readonly catalog = inject(NaiveRagDocumentsCatalogService);
    private readonly chunkPreview = inject(NaiveRagChunkPreviewService);
    private readonly pendingEdits = inject(NaiveRagPendingEditsService);
    private readonly pendingDeletes = inject(NaiveRagPendingDeletesService);

    public pending = this.pendingEdits.pending;
    public pendingDocIds = this.pendingEdits.pendingDocIds;
    public pendingDeleteIds = this.pendingDeletes.pendingDeleteIds;
    public documentStates = this.chunkPreview.documentStates;

    public documents = computed<TableDocument[]>(() => {
        const pending = this.pendingEdits.pending();
        const pendingDelete = this.pendingDeletes.pendingDeleteIds();
        return this.catalog
            .savedDocs()
            .filter((d) => !pendingDelete.has(d.naive_rag_document_id))
            .map((d) => {
                const patch = pending.get(d.naive_rag_document_id);
                if (!patch) return d;
                return { ...d, ...patch } as TableDocument;
            });
    });

    public fetchDocumentConfigs(naiveRagId: number): Observable<TableDocument[]> {
        return this.catalog
            .fetchDocumentConfigs(naiveRagId)
            .pipe(tap((documents) => this.chunkPreview.initDocumentStatesMap(documents)));
    }

    public updateDocumentsFromConfigs(configs: NaiveRagDocumentConfig[]): void {
        const documents = this.catalog.mergeServerConfigs(configs);
        const presentIds = new Set(documents.map((d) => d.naive_rag_document_id));
        this.pendingEdits.pruneOrphans(presentIds);
        this.pendingDeletes.pruneOrphans(presentIds);
        this.chunkPreview.syncStatesWithDocs(documents);
        // If polling brought new saved params, effective params may have
        // changed — reconcile every present doc.
        for (const doc of this.documents()) {
            this.reconcileChunkStatus(doc.naive_rag_document_id);
        }
    }

    public fetchChunks(
        naiveRagId: number,
        documentId: number,
        startOffset: number = 0
    ): Observable<GetNaiveRagDocumentChunksResponse> {
        const doc = this.documents().find((d) => d.naive_rag_document_id === documentId);
        const docParams = doc ? { chunkStrategy: doc.chunk_strategy, chunkOverlap: doc.chunk_overlap } : undefined;
        return this.chunkPreview.fetchChunks(naiveRagId, documentId, startOffset, docParams);
    }

    public loadNextChunks(
        naiveRagId: number,
        documentId: number,
        offset: number,
        limit: number,
        bufferLimit: number
    ): Observable<{ removedCount: number; fetchedCount: number }> {
        return this.chunkPreview.loadNextChunks(naiveRagId, documentId, offset, limit, bufferLimit);
    }

    public loadPrevChunks(
        naiveRagId: number,
        documentId: number,
        offset: number,
        limit: number,
        bufferLimit: number
    ): Observable<{ removedCount: number; fetchedCount: number }> {
        return this.chunkPreview.loadPrevChunks(naiveRagId, documentId, offset, limit, bufferLimit);
    }

    public stopChunking(ragId: number, documentId: number): Observable<CancelNaiveNaiveRagChunkingResponse> {
        const body = this.buildFullParamsBody(documentId);
        if (!body) return EMPTY;
        return this.chunkPreview.stopChunking(ragId, documentId, body);
    }

    public runChunking(ragId: number, documentId: number): Observable<NaiveRagChunkingResponse> {
        const body = this.buildFullParamsBody(documentId);
        if (!body) return EMPTY;
        return this.chunkPreview.runChunking(ragId, documentId, body);
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

    public setPendingField(documentId: number, field: PendingField, value: string | number | null): void {
        const saved = this.catalog.find(documentId);
        if (!saved) return;
        this.pendingEdits.setPendingField(documentId, field, value, saved[field]);
        this.reconcileChunkStatus(documentId);
    }

    public setPendingFields(documentId: number, patch: UpdateNaiveRagDocumentDtoRequest): void {
        const baseline = this.catalog.find(documentId);
        if (!baseline) return;
        this.pendingEdits.setPendingFields(documentId, patch, baseline as unknown as Record<string, unknown>);
        this.reconcileChunkStatus(documentId);
    }

    public clearPending(documentIds: number[]): void {
        if (!documentIds.length) return;
        this.catalog.uncheckAndClearErrors(documentIds);
        this.pendingEdits.dropPending(documentIds);
        for (const id of documentIds) {
            this.reconcileChunkStatus(id);
        }
    }

    public bulkPartialUpdate(ragId: number, docIds: number[]): Observable<BulkUpdateNaiveRagDocumentsResponse> {
        if (!docIds.length) return EMPTY;

        const pendingMap = this.pendingEdits.pending();
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

    public toggleAll(all: boolean, ids?: number[]) {
        this.catalog.toggleAll(all, ids);
    }

    public toggleDocument(id: number) {
        this.catalog.toggleDocument(id);
    }

    public markPendingDelete(id: number): void {
        if (!this.pendingDeletes.markPendingDelete(id)) return;
        this.catalog.uncheckIfChecked(id);
    }

    public clearPendingDeletes(): void {
        this.pendingDeletes.clearPendingDeletes();
    }

    public bulkDeletePending(ragId: number): Observable<BulkDeleteNaiveRagDocumentDtoResponse> {
        return this.pendingDeletes
            .bulkDeletePending(ragId)
            .pipe(tap((response) => this.applyBulkDeleteToRelatedState(response.deleted_config_ids)));
    }

    private handleBulkPartialUpdate(res: BulkUpdateNaiveRagDocumentsResponse): void {
        const configMap = new Map(res.configs.map((c) => [c.naive_rag_document_id, c]));

        this.catalog.applyServerPatches(configMap);

        const clearedIds: number[] = [];
        for (const [id, updated] of configMap) {
            if (!updated.errors || updated.errors.length === 0) {
                clearedIds.push(id);
            }
        }
        if (clearedIds.length) {
            this.pendingEdits.dropPending(clearedIds);
            this.catalog.uncheck(clearedIds);
        }

        for (const docId of configMap.keys()) {
            this.reconcileChunkStatus(docId);
        }
    }

    private applyBulkDeleteToRelatedState(deletedIds: number[]): void {
        if (!deletedIds.length) return;
        this.catalog.removeDocs(deletedIds);
        this.pendingEdits.dropPending(deletedIds);
        this.chunkPreview.removeDocsFromState(deletedIds);
    }

    private reconcileChunkStatus(documentId: number): void {
        const doc = this.documents().find((d) => d.naive_rag_document_id === documentId);
        if (!doc) return;
        const params: ChunkedWithParams = {
            chunk_strategy: doc.chunk_strategy,
            chunk_size: doc.chunk_size,
            chunk_overlap: doc.chunk_overlap,
            additional_params: doc.additional_params,
        };
        this.chunkPreview.reconcileStatus(documentId, params);
    }

    clear(): void {
        this.catalog.clear();
        this.pendingEdits.clear();
        this.pendingDeletes.clear();
        this.chunkPreview.clear();
    }
}
