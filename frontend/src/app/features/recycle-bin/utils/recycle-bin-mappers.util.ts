import { NodeListItem } from '@shared/components';

import { RECYCLE_BIN_SOURCE_KINDS, STORAGE_ITEM_KINDS } from '../constants/recycle-bin-sources.constants';
import {
    GetRecycleBinContentResponse,
    GetRecycleBinDetailResponse,
    GetRecycleBinEntryResponse,
    GetStorageRecycleBinEntryResponse,
    RecycleBinDetail,
    RecycleBinItem,
    RecycleBinResourceSourceKey,
    RecycleBinRestoreOutcome,
    RecycleBinSourceKey,
    RestoreRecycleBinItemResponse,
} from '../models/recycle-bin.model';

/** Shown for a content without a name (decision-table nodes allow a blank one). */
export const UNNAMED_CONTENT = 'Unnamed';

export function toRecycleBinItem(
    source: RecycleBinResourceSourceKey,
    entry: GetRecycleBinEntryResponse
): RecycleBinItem {
    return baseItem(source, RECYCLE_BIN_SOURCE_KINDS[source], entry);
}

export function toStorageRecycleBinItem(entry: GetStorageRecycleBinEntryResponse): RecycleBinItem {
    return {
        ...baseItem('storage', STORAGE_ITEM_KINDS[entry.item_type], entry),
        displayName: storageOwnName(entry.name),
    };
}

/** A source's contents as list rows: a storage folder's as a tree, the others in the order sent. */
export function toContents(
    source: RecycleBinSourceKey,
    contents: readonly GetRecycleBinContentResponse[]
): NodeListItem[] {
    if (source === 'storage') return toFolderTree(contents);
    return contents.map((content, index) => toContentItem(content, index));
}

/**
 * A folder's contents as a tree: each item under its parent, indented by depth and named by its own
 * name. The backend sends paths relative to the folder (`sub/`, `sub/b.txt`); they are sorted here by
 * segment, so a subfolder's items follow it whatever the database's collation does with "/".
 */
export function toFolderTree(contents: readonly GetRecycleBinContentResponse[]): NodeListItem[] {
    return contents
        .map((content) => ({ content, segments: content.name.split('/').filter((segment) => segment !== '') }))
        .sort((first, second) => compareSegments(first.segments, second.segments))
        .map(({ content, segments }) => ({
            name: storageOwnName(content.name),
            nodeType: content.kind,
            key: content.name,
            depth: Math.max(segments.length - 1, 0),
        }));
}

function compareSegments(first: readonly string[], second: readonly string[]): number {
    const shared = Math.min(first.length, second.length);
    for (let index = 0; index < shared; index++) {
        if (first[index] !== second[index]) return first[index] < second[index] ? -1 : 1;
    }
    return first.length - second.length;
}

/** The last segment of a storage path; a folder keeps its trailing slash: `docs/old/` → `old/`. */
export function storageOwnName(path: string): string {
    const isFolder = path.endsWith('/');
    const segments = path.split('/').filter((segment) => segment !== '');
    const ownName = segments.at(-1) ?? path;
    return isFolder ? `${ownName}/` : ownName;
}

export function toRestoreOutcome(
    source: RecycleBinSourceKey,
    response: RestoreRecycleBinItemResponse
): RecycleBinRestoreOutcome {
    return { source, name: response.name, renamedFrom: response.renamed_from };
}

/** Sort comparator: newest `deletedAt` first, then higher id first (the backend's own order). */
export function newestFirst(first: RecycleBinItem, second: RecycleBinItem): number {
    return second.deletedAt.getTime() - first.deletedAt.getTime() || second.id - first.id;
}

/**
 * Kinds are kept as sent: an unknown one still shows (with a generic icon and its raw kind). The key is
 * the position: names repeat (blank decision-table nodes all show as "Unnamed").
 */
function toContentItem(content: GetRecycleBinContentResponse, index: number): NodeListItem {
    return { name: content.name || UNNAMED_CONTENT, nodeType: content.kind, key: `${content.kind}-${index}` };
}

/** A value that doesn't parse in its format is shown as text rather than dropped. */
export function toRecycleBinDetail(detail: GetRecycleBinDetailResponse): RecycleBinDetail {
    const { label, value, format } = detail;
    if (value === null) return { label, format: 'empty', value: null };
    if (format === 'date') {
        const date = new Date(String(value));
        if (!Number.isNaN(date.getTime())) return { label, format, value: date };
    }
    if (format === 'size' && typeof value === 'number' && Number.isFinite(value)) {
        return { label, format, value };
    }
    if (format === 'notice') return { label, format, value: String(value) };
    return { label, format: 'text', value: String(value) };
}

function baseItem(source: RecycleBinSourceKey, kind: string, entry: GetRecycleBinEntryResponse): RecycleBinItem {
    return {
        key: `${source}-${entry.id}`,
        id: entry.id,
        source,
        name: entry.name,
        displayName: entry.name,
        kind,
        deletedAt: new Date(entry.deleted_at),
        daysLeft: entry.days_left,
        details: entry.details.map(toRecycleBinDetail),
        contents: toContents(source, entry.contents),
        contentsTotal: entry.contents_total,
    };
}
