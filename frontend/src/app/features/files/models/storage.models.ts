export interface StorageItem {
    id?: number | null;
    name: string;
    path: string;
    type: 'file' | 'folder';
    is_empty?: boolean;
    size?: number;
    modified?: string;
    children?: StorageItem[];
    isExpanded?: boolean;
}

export interface StorageFileRecord {
    id: number;
    path: string;
    name: string;
    item_type: 'file' | 'folder';
    size: number | null;
    s3_modified: string | null;
    is_system: boolean;
    parent_path: string;
    created_at: string;
    updated_at: string;
}

export interface StorageTreeNode {
    id: number | null;
    name: string;
    path: string;
    type: 'file' | 'folder';
    size: number;
    modified: string | null;
    children: StorageTreeNode[] | null;
}

export interface StorageTreeResponse {
    path: string;
    truncated: boolean;
    tree: StorageTreeNode;
}

export interface StorageGraph {
    id: number;
    name: string;
}

export interface StorageItemInfo extends StorageItem {
    content_type?: string;
    created?: string;
    etag?: string;
    graphs?: StorageGraph[];
}

export interface StorageFileUploadResult {
    type: 'file';
    path: string;
    size: number;
}

export interface StorageArchiveUploadResult {
    type: 'archive';
    extracted: string[];
}

export type StorageUploadResult = StorageFileUploadResult | StorageArchiveUploadResult;

export interface UploadedFile {
    file: File;
    result: StorageUploadResult;
}

export interface UploadFailure {
    file: File;
    error: unknown;
}

/** How a multi-file upload ended: every file lands in exactly one of the two lists. */
export interface StorageUploadBatchResult {
    uploaded: UploadedFile[];
    failed: UploadFailure[];
}

/** One file streamed to POST storage/upload/stream: `size` on a plain file,
 *  `extracted` when the backend unpacked an archive into a new folder. */
export interface StorageStreamUploadResponse {
    status: 'DONE';
    path: string;
    size?: number;
    extracted?: string[];
}

/** How one file of a batch ended: its result, or the error it failed with. */
export type StorageUploadOutcome =
    | { ok: true; file: File; result: StorageUploadResult }
    | { ok: false; file: File; error: unknown };

/** GET storage/upload-limits/: sizes in bytes. */
export interface StorageUploadLimits {
    /** Null when plain files are not capped. */
    max_file_size: number | null;
    /** Applies to names the backend treats as archives (see isArchiveForLimits). */
    max_archive_size: number;
    /** Room left in the organization's storage; changes after every upload. */
    free_bytes: number;
    /** Lower-case with a leading dot (".tar.gz"). Older backends omit both lists. */
    archive_suffixes: string[];
    /** Names ending in one of these are never archives, even when they end in an archive suffix (".docx"). */
    document_extensions: string[];
}

export interface SessionOutputFile {
    id: number;
    path: string;
    name: string;
    added_at: string;
    size?: number;
}

export interface GraphFileRecord {
    id: number;
    graph_id: number;
    path: string;
    added_at: string;
}

export type StorageAction = 'read' | 'write' | 'read_write';

export interface ProjectStorageConfig {
    enabled: boolean;
    action: StorageAction;
    files: string[];
}
