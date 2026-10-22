import { ConfirmationDialogData } from '@shared/components';
import { escapeHtml } from '@shared/utils';
import { catchError, map, Observable, of } from 'rxjs';

import { IndexingEstimate } from '../models/base-rag.model';
import { getIndexingEstimateHtml } from './format-indexing-estimate.util';

export const ESTIMATING_USAGE_HTML = '<div class="dialog-callout dialog-callout--pending">Estimating usage…</div>';

export interface IndexingDocumentInfo {
    configId: number;
    fileName: string;
    wasIndexed: boolean;
}

export function getIndexingConfirmationData(documents: IndexingDocumentInfo[]): ConfirmationDialogData {
    const newDocs = documents.filter((d) => !d.wasIndexed);
    const reindexDocs = documents.filter((d) => d.wasIndexed);
    const hasReindexDocs = reindexDocs.length > 0;

    if (hasReindexDocs) {
        const sections: string[] = [];

        if (reindexDocs.length) {
            const reindexListHtml = reindexDocs.map((d) => `<li>• ${escapeHtml(d.fileName)}</li>`).join('');
            sections.push(
                `<details><summary>Re-indexing <strong>${reindexDocs.length}</strong> file(s)</summary> \n
                      <ul>${reindexListHtml}</ul></details>`
            );
        }

        if (newDocs.length) {
            const newListHtml = newDocs.map((d) => `<li>• ${escapeHtml(d.fileName)}</li>`).join('');
            sections.push(
                `<details><summary>Indexing <strong>${newDocs.length}</strong> new file(s)</summary> \n
                      <ul>${newListHtml}</ul></details>`
            );
        }

        return {
            title: 'Confirm Indexing',
            message:
                "This operation consumes <strong>tokens</strong> based on your provider's plan. Processing time varies from <strong>seconds</strong> to <strong>hours</strong> depending on data volume.",
            caution: sections.join(''),
            type: 'warning',
            cancelText: 'Cancel',
            confirmText: 'Start Indexing',
        };
    }

    const filesText = documents.length ? ` for <strong>${documents.length}</strong> file(s)` : '';

    return {
        title: 'Confirm Indexing',
        message: `Initializing indexing${filesText}. This process involves document parsing, chunking, and generating vector embeddings via <strong>LLM services</strong>.`,
        caution:
            "This operation consumes <strong>tokens</strong> based on your provider's plan. Processing time varies from <strong>seconds</strong> to <strong>hours</strong> depending on data volume.",
        type: 'warning',
        cancelText: 'Later',
        confirmText: 'Start Indexing',
    };
}

/**
 * Opens straight away with an "Estimating usage…" line; the line is replaced once the estimate arrives.
 * A missing or failed estimate removes the line, so indexing is never blocked.
 */
export function getIndexingConfirmationDataWithEstimate(
    documents: IndexingDocumentInfo[],
    estimate$: Observable<IndexingEstimate | null>
): ConfirmationDialogData {
    return {
        ...getIndexingConfirmationData(documents),
        footerMessage: ESTIMATING_USAGE_HTML,
        footerMessageUpdates: estimate$.pipe(
            catchError(() => of(null)),
            map((estimate) => getIndexingEstimateHtml(estimate))
        ),
    };
}
