import { ApiErrorItem } from '@shared/models';
import { Observable } from 'rxjs';

/** A file the user is about to index; `wasIndexed` puts it under "Re-index files". */
export interface IndexingDocumentInfo {
    configId: number;
    fileName: string;
    wasIndexed: boolean;
}

export interface RagConfiguration {
    getConfigurationData(): unknown;
    getIndexingDocuments(): IndexingDocumentInfo[];
    shouldSaveConfig?(): boolean;
    setServerValidationErrors?(errors: ApiErrorItem[]): void;
    // Optional list of document_ids that must be deleted (bulk) before saving
    // the config and starting indexing. Empty / undefined = nothing to delete.
    getPendingDeleteDocumentIds?(): number[];
    // Optional: persist per-document pending edits for the currently-checked
    // documents before indexing runs.
    uploadPendingForChecked?(): Observable<unknown>;
    // Optional: after `uploadPendingForChecked`, indicates any of the checked
    // documents came back with per-field save errors. Callers must abort
    // indexing in that case.
    hasFailedSavesForChecked?(): boolean;
}
