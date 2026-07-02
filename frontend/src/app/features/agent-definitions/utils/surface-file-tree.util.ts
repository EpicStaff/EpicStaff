import { SurfaceFileDisplayRow, SurfaceFileRow, SurfaceFileStats } from '../models/surface-card.model';

interface FileTreeNode {
    name: string;
    path: string;
    type: 'folder' | 'file';
    file?: SurfaceFileRow;
    children: FileTreeNode[];
}

function filePathParts(file: SurfaceFileRow): string[] {
    const raw = (file.path || file.name).replace(/\/+$/, '');
    return raw.split('/').filter(Boolean);
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

function buildFileTree(files: SurfaceFileRow[]): FileTreeNode[] {
    const root: FileTreeNode[] = [];
    const folderMap = new Map<string, FileTreeNode>();

    for (const file of files) {
        const parts = filePathParts(file);
        if (parts.length === 0) continue;

        let parentChildren = root;
        let currentPath = '';

        for (let i = 0; i < parts.length - 1; i++) {
            currentPath = currentPath ? `${currentPath}/${parts[i]}` : parts[i];
            let folder = folderMap.get(currentPath);
            if (!folder) {
                folder = {
                    name: parts[i],
                    path: currentPath,
                    type: 'folder',
                    children: [],
                };
                folderMap.set(currentPath, folder);
                parentChildren.push(folder);
            }
            parentChildren = folder.children;
        }

        const leafName = parts[parts.length - 1];
        parentChildren.push({
            name: file.name || leafName,
            path: file.path || leafName,
            type: 'file',
            file,
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
    files: SurfaceFileRow[],
    collapsedPaths: ReadonlySet<string>
): SurfaceFileDisplayRow[] {
    const rows: SurfaceFileDisplayRow[] = [];
    flattenTree(buildFileTree(files), 0, collapsedPaths, rows);
    return rows;
}

export function countSurfaceFileFolders(files: SurfaceFileRow[]): number {
    const folderPaths = new Set<string>();

    for (const file of files) {
        const parts = filePathParts(file);
        let current = '';
        for (let i = 0; i < parts.length - 1; i++) {
            current = current ? `${current}/${parts[i]}` : parts[i];
            folderPaths.add(current);
        }
    }

    return folderPaths.size;
}

export function buildSurfaceFileStats(files: SurfaceFileRow[]): SurfaceFileStats {
    return {
        folders: countSurfaceFileFolders(files),
        files: files.length,
    };
}

export function filesInFolder(files: SurfaceFileRow[], folderPath: string): SurfaceFileRow[] {
    const prefix = `${folderPath}/`;
    return files.filter((file) => {
        const path = (file.path || file.name).replace(/\/+$/, '');
        return path.startsWith(prefix);
    });
}
