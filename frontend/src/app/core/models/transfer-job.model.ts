import { ExcludedExportItem } from '@shared/models';

import { ImportResult } from './import-result.model';

export type TransferJobStatus = 'queued' | 'running' | 'completed' | 'failed';

export type TransferJobMainEntity = 'Flow' | 'SourceCollection';

/** What an import job brings in: flows or knowledge collections. */
export type TransferImportTarget = 'flows' | 'collections';

export interface TransferJobError {
    code: string;
    message: string;
}

interface TransferJobBase {
    id: string;
    main_entity: TransferJobMainEntity;
    status: TransferJobStatus;
    /** The archive's name once an export has finished; the uploaded name of an import. */
    file_name: string | null;
    error: TransferJobError | null;
    created_at: string;
    finished_at: string | null;
    expires_at: string | null;
}

export interface ExportJobResult {
    /** Dependencies left out because the user may not export them. */
    excluded: ExcludedExportItem[];
}

export interface ExportTransferJob extends TransferJobBase {
    kind: 'export';
    /** Set once the job has completed. */
    result: ExportJobResult | null;
}

export interface ImportTransferJob extends TransferJobBase {
    kind: 'import';
    /** The import summary, set once the job has completed. */
    result: ImportResult | null;
}

export type TransferJob = ExportTransferJob | ImportTransferJob;

export interface TransferJobCreated {
    job_id: string;
}

export interface TransferJobDownloadTicket {
    /** Relative URL carrying a single-use, short-lived ticket; the browser navigates to it. */
    download_url: string;
}
