import { ApiErrorItem } from '@shared/models';
import { Observable } from 'rxjs';

import { IndexingDocumentInfo } from '../helpers/get-indexing-confirmation-data.util';

export interface RagConfiguration {
    getConfigurationData(): unknown;
    getDocumentConfigIds(): number[];
    getIndexingDocuments(): IndexingDocumentInfo[];
    // TODO check is new fields below needed
    shouldSaveConfig(): boolean;
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
