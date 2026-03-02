import { HttpErrorResponse } from "@angular/common/http";
import { inject, Injectable, signal } from "@angular/core";
import { EMPTY, filter, Observable, throwError } from "rxjs";
import { catchError, map, tap } from "rxjs/operators";
import {
    DocFieldChange, TableDocument,
} from "../components/rag-configuration/configuration-table/configuration-table.interface";
import { calcLimit } from "../helpers/calculate-chunks-fetch-limit.util";
import { normalizeBulkUpdateErrors } from "../helpers/normalize-bulk-update-errors.util";
import { transformToTableDocuments } from "../helpers/transform-to-table-document.util";
import {
    DocumentChunkingState,
    DocumentWithChunksStatus,
    GetNaiveRagDocumentChunksResponse, NaiveRagChunkingResponse, NaiveRagDocumentChunk
} from "../models/naive-rag-chunk.model";
import {
    BulkDeleteNaiveRagDocumentDtoResponse,
    BulkUpdateNaiveRagDocumentDtoResponse,
    UpdateNaiveRagDocumentDtoRequest,
    UpdateNaiveRagDocumentResponse
} from "../models/naive-rag-document.model";
import { NaiveRagService } from "./naive-rag.service";

@Injectable({
    providedIn: 'root'
})
export class NaiveRagDocumentsStorageService {
    private documentsSignal = signal<TableDocument[]>([]);
    public documents = this.documentsSignal.asReadonly();

    private documentStatesSignal = signal<Map<number, DocumentChunkingState>>(new Map());
    public documentStates = this.documentStatesSignal.asReadonly();

    private readonly naiveRagService = inject(NaiveRagService);

    public fetchDocumentConfigs(naiveRagId: number): Observable<TableDocument[]> {
        return this.naiveRagService.getDocumentConfigs(naiveRagId)
            .pipe(
                map(({ configs }) => transformToTableDocuments(configs)),
                tap(documents => this.initDocumentStatesMap(documents)),
                tap(documents => this.documentsSignal.set(documents)),
                catchError((err) => throwError(() => err)),
            );
    }

    public fetchChunks(
        naiveRagId: number,
        documentId: number,
    ): Observable<GetNaiveRagDocumentChunksResponse> {
        this.updateDocState(documentId, s => ({ ...s, status: 'fetching_chunks' }));

        const docChunkSize = this.documentsSignal().find(d => d.naive_rag_document_id === documentId)?.chunk_size;
        const limit = docChunkSize ? calcLimit(docChunkSize) : 50;

        return this.naiveRagService.getChunkPreview(naiveRagId, documentId, 0, limit).pipe(
            tap(({ chunks, total_chunks }) => {
                const state = this.documentStates().get(documentId);
                // document was updated during fetching
                if (state?.status === 'chunks_outdated') return;

                const docData = this.documents().find(d => d.naive_rag_document_id === documentId);
                if (!docData) return;

                this.updateDocState(documentId, s => ({
                    ...s,
                    status: 'chunks_ready',
                    chunkStrategy: docData.chunk_strategy,
                    chunkOverlap: docData.chunk_overlap,
                    chunkSize: this.calcAvgChunkSize(chunks),
                    total: total_chunks,
                    chunks
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
    ): Observable<{ removedCount: number, fetchedCount: number }> {
        return this.naiveRagService.getChunkPreview(naiveRagId, documentId, offset, limit).pipe(
            map(({ chunks }) => {
                let removedCount: number = 0;
                // Update doc state in two steps prevents breaking scroll position
                this.updateDocState(documentId, s => ({
                    ...s,
                    removedCount,
                    chunkSize: this.calcAvgChunkSize([...s.chunks, ...chunks]),
                    chunks: [...s.chunks, ...chunks]
                }));
                setTimeout(() => {
                    this.updateDocState(documentId, s => {
                        const updatedChunks = s.chunks;
                        if (updatedChunks.length > bufferLimit) {
                            removedCount = updatedChunks.length - bufferLimit;
                            updatedChunks.splice(0, removedCount);
                        }
                        return { ...s, removedCount, chunks: updatedChunks };
                    });
                }, 100)

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
    ): Observable<{ removedCount: number, fetchedCount: number }> {
        return this.naiveRagService.getChunkPreview(naiveRagId, documentId, offset, limit)
            .pipe(
                map(({ chunks }) => {
                    let removedCount: number = 0;
                    this.updateDocState(documentId, s => {
                        let updatedChunks = [...chunks, ...s.chunks];
                        if (updatedChunks.length > bufferLimit) {
                            removedCount = updatedChunks.length - bufferLimit;
                            updatedChunks.splice(updatedChunks.length - removedCount, removedCount);
                        }
                        return {
                            ...s,
                            removedCount,
                            chunkSize: this.calcAvgChunkSize(updatedChunks),
                            chunks: updatedChunks
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
        documents.forEach(doc => {
            let status: DocumentWithChunksStatus;

            switch (doc.status) {
                case 'new':
                case 'chunking':
                case 'chunked': // document-config status 'chunked' does not represent is chunks up-to-date
                case 'completed':
                    status = 'new';
                    break;
                default:
                    status = 'chunking_failed';
            }

            docStateMap.set(doc.naive_rag_document_id, {
                id: doc.naive_rag_document_id,
                status: status,
                chunkOverlap: doc.chunk_overlap,
                chunkSize: doc.chunk_size,
                chunkStrategy: doc.chunk_strategy,
                total: 0,
                removedCount: 0,
                chunks: [],
            });
        });
        this.documentStatesSignal.set(docStateMap);
    }

    runChunking(ragId: number, documentId: number): Observable<NaiveRagChunkingResponse> {
        const initialState = this.documentStates().get(documentId);
        if (!initialState) return EMPTY;

        this.updateDocState(documentId, s => ({ ...s, status: 'chunking' }));

        return this.naiveRagService.runChunkingProcess(ragId, documentId).pipe(
            tap((res) => {
                const state = this.documentStates().get(documentId);
                if (state?.status === 'chunks_outdated') return;

                switch (res.status) {
                    case 'completed': {
                        this.updateDocState(documentId, s => ({ ...s, status: 'chunked' }));
                        return;
                    }
                    case 'canceled': {
                        return;
                    }
                    case 'failed': {
                        this.updateDocState(documentId, s => ({ ...s, status: 'chunking_failed' }));
                        return;
                    }
                    case 'timeout': {
                        this.updateDocState(documentId, s => ({ ...s, status: 'chunking_failed' }));
                        return;
                    }
                }
            }),
        )
    }

    public updateDocumentField(naiveRagId: number, change: DocFieldChange): Observable<UpdateNaiveRagDocumentResponse> {
        const { documentId, field, value } = change;
        if (value === null) return EMPTY;

        return this.naiveRagService.updateDocumentConfigById(
            naiveRagId,
            documentId,
            { [field]: value }
        ).pipe(
            tap(response => this.handleUpdateSuccess(response)),
            catchError(err => {
                this.handleUpdateError(err, field, documentId)
                return throwError(() => err)
            })
        );
    }

    public updateDocumentFields(
        naiveRagId: number,
        documentId: number,
        data: UpdateNaiveRagDocumentDtoRequest,
    ): Observable<UpdateNaiveRagDocumentResponse> {
        return this.naiveRagService.updateDocumentConfigById(
            naiveRagId,
            documentId,
            data
        ).pipe(
            tap(response => this.handleUpdateSuccess(response)),
            catchError(err => {
                return throwError(() => err)
            })
        );
    }

    public toggleAll(all: boolean) {
        this.documentsSignal.update(items => items.map(i => ({ ...i, checked: !all })));
    }

    public toggleDocument(id: number) {
        this.documentsSignal.update(items => items.map(i => {
            return i.naive_rag_document_id === id ? { ...i, checked: !i.checked } : i
        }));
    }

    public bulkEditDocConfigs(
        ragId: number,
        config_ids: number[],
        dto: UpdateNaiveRagDocumentDtoRequest
    ): Observable<BulkUpdateNaiveRagDocumentDtoResponse> {
        if (!config_ids.length) return EMPTY;

        return this.naiveRagService.bulkUpdateDocumentConfigs(
            ragId,
            { config_ids, ...dto }
        ).pipe(
            tap((response) => this.hangleBulkEdit(response)),
            catchError(err => throwError(() => err))
        );
    }

    public bulkDeleteDocConfigs(
        ragId: number,
        config_ids: number[]
    ): Observable<BulkDeleteNaiveRagDocumentDtoResponse> {
        if (!config_ids.length) return EMPTY;

        return this.naiveRagService
            .bulkDeleteDocumentConfigs(ragId, { config_ids })
            .pipe(
                tap(response => this.handleSuccessBulkDelete(response)),
                catchError(err => throwError(() => err)),
            );
    }

    private updateDocState(
        ragDocId: number,
        updater: (state: DocumentChunkingState) => DocumentChunkingState
    ): void {
        this.documentStatesSignal.update(prevMap => {
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

        this.documentStatesSignal.update(prevMap => {
            const newMap = new Map(prevMap);

            for (const id of ragDocIds) {
                newMap.delete(id);
            }

            return newMap;
        });
    }

    // handlers
    private handleUpdateSuccess(response: UpdateNaiveRagDocumentResponse) {
        const { config } = response;

        this.documentsSignal.update(items =>
            items.map(i =>
                i.document_id === config.document_id ? { ...i, ...config, errors: {} } : i
            )
        );

        this.updateDocState(config.naive_rag_document_id, s => ({
            ...s,
            status: s.status !== 'new' ? 'chunks_outdated' : s.status,
            chunkStrategy: config.chunk_strategy,
            chunkSize: config.chunk_size,
            // Update overlap only after chunk fetching
            // chunkOverlap: config.chunk_overlap,
            total: config.total_chunks,
        }));
    }

    private handleUpdateError(
        error: HttpErrorResponse,
        field: keyof TableDocument,
        documentId: number
    ) {
        // Update of one field will return array with 1 error
        const [err] = error.error.errors;

        if (!err) return;

        this.documentsSignal.update(items =>
            items.map(item => {
                return item.naive_rag_document_id === documentId ? {
                    ...item,
                    errors: { [field]: { reason: err.reason } }
                } : item;
            })
        );
    }

    private hangleBulkEdit(res: BulkUpdateNaiveRagDocumentDtoResponse) {
        const configMap = new Map(
            res.configs.map(c => [c.naive_rag_document_id, c])
        );

        this.documentsSignal.update(items =>
            items.map(item => {
                const updated = configMap.get(item.naive_rag_document_id);
                if (!updated) return item;

                return {
                    ...item,
                    ...updated,
                    errors: normalizeBulkUpdateErrors(updated.errors)
                };
            })
        );

        this.documentStatesSignal.update(prevMap => {
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

    private handleSuccessBulkDelete(res: BulkDeleteNaiveRagDocumentDtoResponse) {
        const deletedIds = res.deleted_config_ids;
        this.documentsSignal.update(items => items.filter(i => {
            return !deletedIds.includes(i.naive_rag_document_id);
        }));
        this.removeDocsFromState(deletedIds);
    }
}
