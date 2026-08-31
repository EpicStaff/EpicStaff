import { inject, Injectable, signal } from '@angular/core';
import { Observable, throwError } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';

import {
    NormalizedDocumentErrors,
    TableDocument,
} from '../components/naive-rag-configuration/configuration-table/configuration-table.interface';
import { normalizeBulkUpdateErrors } from '../helpers/normalize-bulk-update-errors.util';
import { transformToTableDocuments } from '../helpers/transform-to-table-document.util';
import { NaiveRagDocumentConfig, UpdatedNaiveRagDocumentConfig } from '../models/naive-rag-document.model';
import { NaiveRagService } from './naive-rag.service';

/**
 * Owns the baseline "docs from server" list. Handles the fetch HTTP,
 * polling merges, and table-level presentation ops (check/toggle,
 * unchecking rows, clearing per-row errors, removing docs after delete).
 */
@Injectable({
    providedIn: 'root',
})
export class NaiveRagDocumentsCatalogService {
    private readonly naiveRagService = inject(NaiveRagService);

    private savedDocsSignal = signal<TableDocument[]>([]);
    public savedDocs = this.savedDocsSignal.asReadonly();

    public fetchDocumentConfigs(naiveRagId: number): Observable<TableDocument[]> {
        return this.naiveRagService.getDocumentConfigs(naiveRagId).pipe(
            map(({ configs }) => transformToTableDocuments(configs)),
            tap((documents) => this.savedDocsSignal.set(documents)),
            catchError((err) => throwError(() => err))
        );
    }

    public mergeServerConfigs(configs: NaiveRagDocumentConfig[]): TableDocument[] {
        const itemMap = new Map(this.savedDocsSignal().map((d) => [d.naive_rag_document_id, d]));

        const documents = configs.map((config) => {
            const item = itemMap.get(config.naive_rag_document_id);
            return item ? { ...item, ...config } : { ...config, checked: false };
        });
        this.savedDocsSignal.set(documents);
        return documents;
    }

    public applyServerPatches(updates: Map<number, UpdatedNaiveRagDocumentConfig>): void {
        this.savedDocsSignal.update((items) =>
            items.map((item) => {
                const updated = updates.get(item.naive_rag_document_id);
                if (!updated) return item;
                return {
                    ...item,
                    ...updated,
                    errors: normalizeBulkUpdateErrors(updated.errors),
                };
            })
        );
    }

    public setDocErrors(documentId: number, errors: NormalizedDocumentErrors): void {
        this.savedDocsSignal.update((items) =>
            items.map((item) => (item.naive_rag_document_id === documentId ? { ...item, errors } : item))
        );
    }

    public uncheck(ids: Iterable<number>): void {
        const idSet = new Set(ids);
        if (idSet.size === 0) return;
        this.savedDocsSignal.update((items) =>
            items.map((i) => (idSet.has(i.naive_rag_document_id) ? { ...i, checked: false } : i))
        );
    }

    /**
     * Unchecks + clears per-row errors. Used when the user fully reverts
     * pending edits via the row-level Revert affordance.
     */
    public uncheckAndClearErrors(ids: Iterable<number>): void {
        const idSet = new Set(ids);
        if (idSet.size === 0) return;
        this.savedDocsSignal.update((items) =>
            items.map((item) => {
                if (!idSet.has(item.naive_rag_document_id)) return item;
                return { ...item, checked: false, errors: item.errors ? {} : item.errors };
            })
        );
    }

    /** Removes docs from the catalog after a successful bulk delete. */
    public removeDocs(ids: Iterable<number>): void {
        const idSet = new Set(ids);
        if (idSet.size === 0) return;
        this.savedDocsSignal.update((items) => items.filter((i) => !idSet.has(i.naive_rag_document_id)));
    }

    /**
     * Marks a single doc as unchecked. Used by soft-delete flow when a
     * doc is stashed for later deletion — it can't remain indexable.
     */
    public uncheckIfChecked(id: number): void {
        this.savedDocsSignal.update((items) =>
            items.map((i) => (i.naive_rag_document_id === id && i.checked ? { ...i, checked: false } : i))
        );
    }

    public toggleAll(all: boolean, ids?: number[]): void {
        const idSet = ids ? new Set(ids) : null;
        this.savedDocsSignal.update((items) =>
            items.map((i) => {
                if (idSet && !idSet.has(i.naive_rag_document_id)) return i;
                return { ...i, checked: !all };
            })
        );
    }

    public toggleDocument(id: number): void {
        this.savedDocsSignal.update((items) =>
            items.map((i) => (i.naive_rag_document_id === id ? { ...i, checked: !i.checked } : i))
        );
    }

    public find(id: number): TableDocument | undefined {
        return this.savedDocsSignal().find((d) => d.naive_rag_document_id === id);
    }

    public clear(): void {
        this.savedDocsSignal.set([]);
    }
}
