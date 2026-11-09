import { ExcludedExportItem } from '@shared/models';

import { ImportResult } from './import-result.model';

export type TransferJobStatus = 'queued' | 'running' | 'completed' | 'failed';

/** What a job does: writes an export archive or reads one in. */
export type TransferJobKind = 'export' | 'import';

/** What a job exports or imports; `FlowNodes` is a selection of nodes exported from the flow editor. */
export type TransferJobMainEntity =
    | 'Flow'
    | 'SourceCollection'
    | 'PythonCodeTool'
    | 'MCPTool'
    | 'AuditFilterPreset'
    | 'Session'
    | 'ClassificationDecisionTableNode'
    | 'FlowNodes';

/** The two formats an export of sessions or of a classification decision table can be written in. */
export type ExportFormat = 'json' | 'csv';

/** `error.code` of a completed export whose archive was deleted to make room for the user's newer exports. */
export const ARCHIVE_REMOVED_ERROR_CODE = 'archive_removed';

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
    /** What the job is about, for a person: the item's name, a count such as "3 tools", or the uploaded file's name. */
    display_name: string;
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

/** A page of the user's jobs in the active organization, newest first. */
export interface TransferJobPage {
    count: number;
    results: TransferJob[];
}

export interface TransferJobListFilter {
    /** Jobs in any of these statuses; every status when left out. */
    status?: TransferJobStatus[];
    kind?: TransferJobKind;
}

/** Which slice of the list to send; the server's default page when left out. */
export interface TransferJobPageRequest {
    limit?: number;
    offset?: number;
}

export interface TransferJobCreated {
    job_id: string;
}

export interface TransferJobDownloadTicket {
    /** Relative URL carrying a single-use, short-lived ticket; the browser navigates to it. */
    download_url: string;
}

/** The answer to clearing the user's jobs. */
export interface TransferJobsCleared {
    /** How many jobs were deleted; running jobs are kept and not counted. */
    deleted: number;
}

/** What a job is about, for a person. */
export const TRANSFER_JOB_ENTITY_LABELS: Record<TransferJobMainEntity, string> = {
    Flow: 'Flows',
    SourceCollection: 'Knowledge collections',
    PythonCodeTool: 'Custom tools',
    MCPTool: 'MCP tools',
    AuditFilterPreset: 'Audit presets',
    Session: 'Sessions',
    ClassificationDecisionTableNode: 'Classification decision table',
    FlowNodes: 'Flow nodes',
};

export function isUnfinishedTransferJob(job: TransferJob): boolean {
    return job.status === 'queued' || job.status === 'running';
}

/** A completed export whose archive is still kept. */
export function isDownloadableExport(job: TransferJob): job is ExportTransferJob {
    return job.kind === 'export' && job.status === 'completed' && job.error?.code !== ARCHIVE_REMOVED_ERROR_CODE;
}

/** The job's name for a person: what it holds, else what kind of thing it holds. */
export function transferJobName(job: TransferJob): string {
    return job.display_name || TRANSFER_JOB_ENTITY_LABELS[job.main_entity] || 'Transfer';
}
