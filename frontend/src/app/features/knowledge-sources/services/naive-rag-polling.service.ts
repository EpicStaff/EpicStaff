import { inject, Injectable } from '@angular/core';
import { concat, EMPTY, interval, Subject } from 'rxjs';
import { catchError, exhaustMap, last, takeUntil, takeWhile, tap } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications';
import { DocumentsStorageService } from './documents-storage.service';
import { NaiveRagService } from './naive-rag.service';
import { NaiveRagDocumentsStorageService } from './naive-rag-documents-storage.service';

const POLL_INTERVAL_MS = 1500;

@Injectable({
    providedIn: 'root',
})
export class NaiveRagPollingService {
    private naiveRagService = inject(NaiveRagService);
    private documentsStorageService = inject(NaiveRagDocumentsStorageService);
    private documentsStorage = inject(DocumentsStorageService);
    private toastService = inject(ToastService);
    private stopPolling$ = new Subject<void>();

    pollDocumentStatuses(ragId: number, configIds?: number[]): void {
        this.stopPolling$.next();

        const idsToTrack = configIds ?? this.documentsStorageService.documents().map((d) => d.naive_rag_document_id);
        if (!idsToTrack.length) return;

        this.documentsStorageService.setDocumentStatuses(idsToTrack, 'indexing');

        const polls = idsToTrack.map((docId) => {
            const doc = this.documentsStorageService.documents().find((d) => d.naive_rag_document_id === docId);

            return interval(POLL_INTERVAL_MS).pipe(
                exhaustMap(() => this.naiveRagService.getDocumentConfigById(ragId, docId)),
                tap((config) => this.documentsStorageService.updateDocumentFromConfig(config)),
                takeWhile((config) => config.status === 'chunking' || config.status === 'indexing', true),
                last(),
                tap((config) => {
                    if (config.status === 'failed' || config.status === 'warning') {
                        this.toastService.error(`Indexing ${config.file_name} failed: ${config.error_message}`);
                    } else {
                        this.toastService.success(`Indexed: ${config.file_name}`);
                    }
                }),
                catchError(() => {
                    if (!doc || !this.documentsStorage.isDeleting(doc.document_id)) {
                        this.toastService.error(`Polling failed for document config ${docId}`);
                    }
                    return EMPTY;
                })
            );
        });

        concat(...polls)
            .pipe(takeUntil(this.stopPolling$))
            .subscribe();
    }

    stopPolling(): void {
        this.stopPolling$.next();
    }
}
