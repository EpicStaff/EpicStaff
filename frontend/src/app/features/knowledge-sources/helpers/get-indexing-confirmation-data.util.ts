import { ConfirmationDialogData } from '@shared/components';

export interface IndexingDocumentInfo {
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
            const reindexListHtml = reindexDocs.map((d) => `<li>• ${d.fileName}</li>`).join('');
            sections.push(
                `<details><summary>Re-indexing <strong>${reindexDocs.length}</strong> file(s)</summary> \n
                      <ul>${reindexListHtml}</ul></details>`
            );
        }

        if (newDocs.length) {
            const newListHtml = newDocs.map((d) => `<li>• ${d.fileName}</li>`).join('');
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
