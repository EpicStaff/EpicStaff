import { PermTriState } from './surface.model';

export type SurfaceTabId = 'tools' | 'files' | 'collections';

export interface SurfaceToolOption {
    id: number;
    name: string;
    description: string;
    kind: 'python' | 'mcp';
}

export interface SurfaceCollectionOption {
    id: number;
    name: string;
}

export interface SurfaceFilePerms {
    list: PermTriState;
    view: PermTriState;
    edit: PermTriState;
    delete: PermTriState;
}

export interface SurfaceFileRow {
    id: number;
    name: string;
    path: string;
    perms: SurfaceFilePerms;
}

export interface SurfaceFileFolderRow {
    kind: 'folder';
    path: string;
    name: string;
    depth: number;
    expanded: boolean;
}

export interface SurfaceFileItemRow {
    kind: 'file';
    row: SurfaceFileRow;
    depth: number;
}

export type SurfaceFileDisplayRow = SurfaceFileFolderRow | SurfaceFileItemRow;

export interface SurfaceFileStats {
    folders: number;
    files: number;
}

export const SURFACE_FILE_PERM_COLUMNS: { key: keyof SurfaceFilePerms; label: string; icon: string }[] = [
    { key: 'list', label: 'List', icon: 'list' },
    { key: 'view', label: 'View', icon: 'eye' },
    { key: 'edit', label: 'Edit', icon: 'edit' },
    { key: 'delete', label: 'Delete', icon: 'trash' },
];

export function nextPermState(current: PermTriState): PermTriState {
    if (current === 'unset') return 'allow';
    if (current === 'allow') return 'deny';
    return 'unset';
}
