import { StorageItem } from '../models/storage.models';

const ARCHIVE_EXTENSIONS = new Set(['zip', 'tar', 'gz', 'tgz', 'bz2', 'xz']);

export function getFileExtension(name: string): string {
    const trimmed = name.replace(/\.+$/, '');
    const parts = trimmed.split('.');
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : '';
}

export function isArchiveFileName(name: string): boolean {
    const lower = name.toLowerCase();
    if (lower.endsWith('.tar.gz') || lower.endsWith('.tar.bz2') || lower.endsWith('.tar.xz')) {
        return true;
    }
    return ARCHIVE_EXTENSIONS.has(getFileExtension(name));
}

export function filterStorageItems(items: StorageItem[], term: string): StorageItem[] {
    if (!term.trim()) return items;
    const lower = term.toLowerCase();
    const result: StorageItem[] = [];
    for (const item of items) {
        if (item.type === 'folder') {
            const filteredChildren = filterStorageItems(item.children ?? [], lower);
            if (filteredChildren.length || item.name.toLowerCase().includes(lower)) {
                result.push({ ...item, children: filteredChildren, isExpanded: filteredChildren.length > 0 });
            }
        } else {
            if (item.name.toLowerCase().includes(lower)) result.push(item);
        }
    }
    return result;
}
