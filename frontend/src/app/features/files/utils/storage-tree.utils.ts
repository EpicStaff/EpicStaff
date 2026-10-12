import { StorageItem, StorageTreeNode } from '../models/storage.models';
import { normalizeStoragePath } from './storage-path.utils';

/** A folder row in a destination-folder picker, built from the full `storage/tree/` response. */
export interface StorageFolderNode {
    name: string;
    path: string;
    level: number;
    isExpanded: boolean;
    /** Has at least one sub-folder, so it can be expanded. */
    hasChildren: boolean;
    /** Holds neither files nor folders. */
    isEmpty: boolean;
    children: StorageFolderNode[];
}

/** Maps tree nodes to storage items; folder paths lose the trailing "/" the tree endpoint returns. */
export function toStorageItems(nodes: StorageTreeNode[] | null): StorageItem[] {
    return (nodes ?? []).map((node) => ({
        id: node.id,
        name: node.name,
        path: normalizeStoragePath(node.path),
        type: node.type,
        size: node.size,
        modified: node.modified ?? undefined,
        is_empty: node.type === 'folder' && !node.children?.length,
        children: node.type === 'folder' ? toStorageItems(node.children) : undefined,
    }));
}

/** Keeps only the folders of the tree, collapsed. */
export function toFolderNodes(nodes: StorageTreeNode[] | null, level = 0): StorageFolderNode[] {
    return (nodes ?? [])
        .filter((node) => node.type === 'folder')
        .map((node) => {
            const children = toFolderNodes(node.children, level + 1);
            return {
                name: node.name,
                path: normalizeStoragePath(node.path),
                level,
                isExpanded: false,
                hasChildren: children.length > 0,
                isEmpty: !node.children?.length,
                children,
            };
        });
}

/** Every folder depth-first, whether expanded or not — the search space of a folder picker. */
export function flattenFolderNodes(nodes: StorageFolderNode[]): StorageFolderNode[] {
    return nodes.flatMap((node) => [node, ...flattenFolderNodes(node.children)]);
}
