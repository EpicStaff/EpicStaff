import { StorageItem } from '../models/storage.models';

export function getFileExtension(name: string): string {
    const trimmed = name.replace(/\.+$/, '');
    const parts = trimmed.split('.');
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : '';
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
