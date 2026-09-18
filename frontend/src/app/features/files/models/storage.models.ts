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

export interface StorageUploadResponse {
    uploaded: StorageUploadResult[];
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
