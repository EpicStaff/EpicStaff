import { SurfaceFileDisplayRow, SurfaceFileRow, SurfaceFileStats } from '../models/surface-card.model';

interface FileTreeNode {
    name: string;
    path: string;
    type: 'folder' | 'file';
    file?: SurfaceFileRow;
    row?: SurfaceFileRow;
    children: FileTreeNode[];
}

function normalizePath(row: SurfaceFileRow): string {
    return (row.path || row.name).replace(/\/+$/, '');
}

function filePathParts(row: SurfaceFileRow): string[] {
    return normalizePath(row).split('/').filter(Boolean);
}

function compareNodes(a: FileTreeNode, b: FileTreeNode): number {
    if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
}

function sortTree(nodes: FileTreeNode[]): FileTreeNode[] {
    return [...nodes]
        .sort(compareNodes)
        .map((node) => (node.type === 'folder' ? { ...node, children: sortTree(node.children) } : node));
}

function ensureFolderChain(
    root: FileTreeNode[],
    folderMap: Map<string, FileTreeNode>,
    parts: string[]
): FileTreeNode[] {
    let parentChildren = root;
    let currentPath = '';
    for (const part of parts) {
        currentPath = currentPath ? `${currentPath}/${part}` : part;
        let folder = folderMap.get(currentPath);
        if (!folder) {
            folder = { name: part, path: currentPath, type: 'folder', children: [] };
            folderMap.set(currentPath, folder);
            parentChildren.push(folder);
        }
        parentChildren = folder.children;
    }
    return parentChildren;
}

function buildFileTree(rows: SurfaceFileRow[]): FileTreeNode[] {
    const root: FileTreeNode[] = [];
    const folderMap = new Map<string, FileTreeNode>();

    for (const row of rows) {
        const parts = filePathParts(row);
        if (parts.length === 0) continue;

        if (row.type === 'folder') {
            ensureFolderChain(root, folderMap, parts.slice(0, -1));
            const fullPath = parts.join('/');
            let node = folderMap.get(fullPath);
            if (!node) {
                node = { name: parts[parts.length - 1], path: fullPath, type: 'folder', children: [] };
                folderMap.set(fullPath, node);
                const parentChildren = ensureFolderChain(root, folderMap, parts.slice(0, -1));
                parentChildren.push(node);
            }
            node.row = row;
            node.name = row.name || node.name;
            continue;
        }

        const parentChildren = ensureFolderChain(root, folderMap, parts.slice(0, -1));
        const leafName = parts[parts.length - 1];
        parentChildren.push({
            name: row.name || leafName,
            path: normalizePath(row),
            type: 'file',
            file: row,
            children: [],
        });
    }

    return sortTree(root);
}

function flattenTree(
    nodes: FileTreeNode[],
    depth: number,
    collapsedPaths: ReadonlySet<string>,
    out: SurfaceFileDisplayRow[]
): void {
    for (const node of nodes) {
        if (node.type === 'folder') {
            const expanded = !collapsedPaths.has(node.path);
            out.push({
                kind: 'folder',
                path: node.path,
                name: node.name,
                depth,
                expanded,
                hasChildren: node.children.length > 0,
                row: node.row,
            });
            if (expanded) flattenTree(node.children, depth + 1, collapsedPaths, out);
            continue;
        }

        if (node.file) {
            out.push({ kind: 'file', row: node.file, depth });
        }
    }
}

export function buildSurfaceFileDisplayRows(
    rows: SurfaceFileRow[],
    collapsedPaths: ReadonlySet<string>
): SurfaceFileDisplayRow[] {
    const out: SurfaceFileDisplayRow[] = [];
    flattenTree(buildFileTree(rows), 0, collapsedPaths, out);
    return out;
}

export function buildSurfaceFileStats(rows: SurfaceFileRow[]): SurfaceFileStats {
    const folderPaths = new Set<string>();
    let files = 0;

    for (const row of rows) {
        if (row.type === 'folder') {
            folderPaths.add(normalizePath(row));
            continue;
        }
        files++;
        // Count the structural parent folders a file passes through.
        const parts = filePathParts(row);
        let current = '';
        for (let i = 0; i < parts.length - 1; i++) {
            current = current ? `${current}/${parts[i]}` : parts[i];
            folderPaths.add(current);
        }
    }

    return { folders: folderPaths.size, files };
}
