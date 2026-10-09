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
 * Filter group of a storage folder's content: its file format, or "Folder". Lets the filter in an
 * expanded folder offer formats instead of File / Folder.
 */
export function storageFormatGroup(content: NodeListItem): string {
    return content.nodeType === 'folder' ? FOLDER_FORMAT_GROUP : fileFormatGroup(content.name);
}

/** Filter group of a collection's document: its file format. */
export function documentFormatGroup(content: NodeListItem): string {
    return fileFormatGroup(content.name);
}
