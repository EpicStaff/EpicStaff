import { NodeListItem } from '@shared/components';

export const FOLDER_FORMAT_GROUP = 'Folder';
/** A file without an extension. */
export const NO_EXTENSION_FORMAT_GROUP = 'No extension';

/** A file's format from its name's extension, upper case (`PDF`, `MD`…). */
export function fileFormatGroup(name: string): string {
    const ownName = name.split('/').at(-1) ?? name;
    const dot = ownName.lastIndexOf('.');
    // A leading dot (".env") is a hidden file's name, not an extension.
    return dot > 0 && dot < ownName.length - 1 ? ownName.slice(dot + 1).toUpperCase() : NO_EXTENSION_FORMAT_GROUP;
}

/**
 * Group of a storage folder's content: its file format, or "Folder". Labels each item of an expanded
 * folder by format instead of File / Folder (a folder shows as a tree, without a filter).
 */
export function storageFormatGroup(content: NodeListItem): string {
    return content.nodeType === 'folder' ? FOLDER_FORMAT_GROUP : fileFormatGroup(content.name);
}

/** Filter group of a collection's document: its file format. */
export function documentFormatGroup(content: NodeListItem): string {
    return fileFormatGroup(content.name);
}
