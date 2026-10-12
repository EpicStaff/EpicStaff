import { AuthorshipFields } from '@shared/models';

// Also built client-side from other shapes (e.g. picker tree nodes), so the read-only author,
// creation time and last-edit fields are optional.
export interface StorageItem extends Partial<AuthorshipFields> {
    id?: number | null;
    name: string;
    path: string;
    type: 'file' | 'folder';
    is_empty?: boolean;
    size?: number;
    modified?: string;
    children?: StorageItem[];
    isExpanded?: boolean;
    /** Read-only ISO 8601 creation time; null for implied folders and untracked entries. */
    created_at?: string | null;
}

export interface StorageFileRecord extends AuthorshipFields {
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

export interface StorageTreeNode extends AuthorshipFields {
    id: number | null;
    name: string;
    path: string;
    type: 'file' | 'folder';
    size: number;
    modified: string | null;
    children: StorageTreeNode[] | null;
    /** Read-only ISO 8601 creation time; null for implied folders and untracked entries. */
    created_at: string | null;
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

/** Result of a multi-file upload: each file is in exactly one list. */
export interface StorageUploadBatchResult {
    uploaded: UploadedFile[];
    failed: UploadFailure[];
}

/** Response of POST storage/upload/stream: `size` for a file, `extracted` for an unpacked archive. */
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
    /** Size cap for archives (see isArchiveForLimits). */
    max_archive_size: number;
    /** Free space left in the organization's storage. */
    free_bytes: number;
    /** Archive suffixes, lower-case with a leading dot (".tar.gz"). */
    archive_suffixes: string[];
    /** Extensions that are never archives, even with an archive suffix (".docx"). */
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
