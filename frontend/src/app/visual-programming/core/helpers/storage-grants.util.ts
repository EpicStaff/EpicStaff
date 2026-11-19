import { ActionCode, NodeType, ResourceCode } from '@shared/models';
import {
    filesPermissionLabel,
    missingStorageGrantActions,
    STORAGE_GRANT_FILES_ACTIONS,
    StorageGrant,
} from '@shared/utils';

import { ClassificationDecisionTableNodeModel, NodeModel } from '../models/node.model';
import {
    CdtStorageGrantFields,
    StorageGrantFields,
    StorageGrants,
    StorageGrantSlot,
} from '../models/storage-grants.model';

export const STORAGE_GRANT_KINDS: readonly StorageGrant[] = ['read', 'write', 'delete'];

export const STORAGE_GRANT_LABELS: Record<StorageGrant, string> = {
    read: 'Read',
    write: 'Write',
    delete: 'Delete',
};

/** The node types whose code the backend gives per-node storage grants. */
const STORAGE_GRANT_NODE_TYPES: ReadonlySet<NodeType> = new Set([
    NodeType.PYTHON,
    NodeType.WEBHOOK_TRIGGER,
    NodeType.CLASSIFICATION_TABLE,
]);

/** The node types whose code always reads the flow's attached files, so changing them needs Files:Read. */
const FLOW_FILE_READING_NODE_TYPES: ReadonlySet<NodeType> = new Set([NodeType.FILE_EXTRACTOR, NodeType.AUDIO_TO_TEXT]);

/** Shown on a file extractor or audio transcription panel that the user may not change. */
export const FILES_READ_LOCK_MESSAGE =
    "This node reads the flow's attached files, so changing it needs Files: Read, which you don't have.";

const NO_ACCESS: StorageGrants = { read: false, write: false, delete: false };

/** Whether the user holds a Files action. */
export type PermissionCheck = (resource: ResourceCode, action: ActionCode) => boolean;

export function hasStorageGrantsForNodeType(type: NodeType): boolean {
    return STORAGE_GRANT_NODE_TYPES.has(type);
}

/**
 * The grants a node created in the editor starts with: none ticked, which the server accepts from any role.
 * Nothing for a type that has no granted code.
 */
export function newNodeStorageGrants(
    type: NodeType
): Pick<ClassificationDecisionTableNodeModel, 'storageGrants' | 'preStorageGrants' | 'postStorageGrants'> {
    if (type === NodeType.CLASSIFICATION_TABLE) {
        return { preStorageGrants: { ...NO_ACCESS }, postStorageGrants: { ...NO_ACCESS } };
    }
    return hasStorageGrantsForNodeType(type) ? { storageGrants: { ...NO_ACCESS } } : {};
}

function columnPrefix(slot: StorageGrantSlot): string {
    return slot === 'main' ? 'storage_grant_' : `${slot}_storage_grant_`;
}

/**
 * The grants of one slot as the server sent them. `undefined` when the server sent none of the three columns
 * (a version snapshot older than grants), so a save leaves them out instead of inventing a value.
 */
export function storageGrantsFromDto(
    dto: StorageGrantFields | CdtStorageGrantFields,
    slot: StorageGrantSlot = 'main'
): StorageGrants | undefined {
    const columns = dto as Record<string, boolean | undefined>;
    const prefix = columnPrefix(slot);
    const read = columns[`${prefix}read`];
    const write = columns[`${prefix}write`];
    const remove = columns[`${prefix}delete`];
    if (read === undefined && write === undefined && remove === undefined) return undefined;
    return { read: read === true, write: write === true, delete: remove === true };
}

/** The three columns of one slot for a save: all of them as held, or none when the node holds no grants. */
export function storageGrantsToPayload(
    grants: StorageGrants | undefined,
    slot: StorageGrantSlot = 'main'
): Record<string, boolean> {
    if (!grants) return {};
    const prefix = columnPrefix(slot);
    return {
        [`${prefix}read`]: grants.read,
        [`${prefix}write`]: grants.write,
        [`${prefix}delete`]: grants.delete,
    };
}

export function getNodeStorageGrants(node: NodeModel, slot: StorageGrantSlot = 'main'): StorageGrants | undefined {
    if (node.type === NodeType.CLASSIFICATION_TABLE) {
        const table = node as ClassificationDecisionTableNodeModel;
        if (slot === 'pre') return table.preStorageGrants;
        if (slot === 'post') return table.postStorageGrants;
        return undefined;
    }
    return slot === 'main' ? node.storageGrants : undefined;
}

export function hasNoStorageAccess(grants: StorageGrants | undefined): boolean {
    return !!grants && STORAGE_GRANT_KINDS.every((kind) => !grants[kind]);
}

/** The grants after the user flips one box. A node that holds none yet starts from every box false. */
export function toggleStorageGrant(
    grants: StorageGrants | undefined,
    kind: StorageGrant,
    value: boolean
): StorageGrants {
    return { ...(grants ?? NO_ACCESS), [kind]: value };
}

export function canSetStorageGrant(kind: StorageGrant, can: PermissionCheck): boolean {
    return STORAGE_GRANT_FILES_ACTIONS[kind].every((action) => can(ResourceCode.Files, action));
}

/**
 * Whether the user may flip one box of a slot with these grants. Unticking is always allowed; ticking needs the
 * permission behind the box.
 */
export function canEditStorageGrant(
    grants: StorageGrants | undefined,
    kind: StorageGrant,
    can: PermissionCheck
): boolean {
    return grants?.[kind] === true || canSetStorageGrant(kind, can);
}

export function storageGrantDisabledTooltip(kind: StorageGrant): string {
    const needed = STORAGE_GRANT_FILES_ACTIONS[kind].map(filesPermissionLabel).join(' and ');
    return `Your role lacks the permission needed to tick this: ${needed}.`;
}

function storageGrantLockMessage(missing: readonly ActionCode[]): string {
    const permissions = missing.map(filesPermissionLabel).join(', ');
    return `This code runs with ${permissions}, which you don't have. You can only untick its file access; contact an admin to change anything else.`;
}

/** Shown instead of the usual lock note while the canvas boxes differ from the saved ones: the server still holds the saved ones. */
export const STORAGE_GRANT_LOCK_SAVE_FIRST_MESSAGE = 'Save your file access changes first, then you can edit the code.';

function sameStorageGrants(first: StorageGrants | undefined, second: StorageGrants | undefined): boolean {
    return STORAGE_GRANT_KINDS.every((kind) => (first?.[kind] ?? false) === (second?.[kind] ?? false));
}

/**
 * The note that locks a slot's code and its steering fields, or `null`: a box ticked in the saved grants (what the
 * server holds) needs a permission the user's own role lacks. The boxes stay enabled for unticking. While the user's
 * permissions are not loaded nothing locks, the server decides. `canvasGrants` are the boxes as they stand on the
 * canvas: when they differ from the saved ones the note tells the user to save first.
 */
export function storageGrantLockOf(
    savedGrants: StorageGrants | undefined,
    can: PermissionCheck,
    arePermissionsLoaded: () => boolean,
    canvasGrants: StorageGrants | undefined = savedGrants
): string | null {
    if (!savedGrants || !arePermissionsLoaded()) return null;
    const ticked = STORAGE_GRANT_KINDS.filter((kind) => savedGrants[kind]);
    const missing = missingStorageGrantActions(ticked, (action) => can(ResourceCode.Files, action));
    if (!missing.length) return null;
    return sameStorageGrants(savedGrants, canvasGrants)
        ? storageGrantLockMessage(missing)
        : STORAGE_GRANT_LOCK_SAVE_FIRST_MESSAGE;
}

/**
 * The note that makes a file extractor or audio transcription read-only, or `null`: their code always reads the
 * flow's attached files, so changing them needs Files:Read. Every other node type has no such lock.
 */
export function filesReadLockOf(
    type: NodeType,
    can: PermissionCheck,
    arePermissionsLoaded: () => boolean
): string | null {
    if (!FLOW_FILE_READING_NODE_TYPES.has(type) || !arePermissionsLoaded()) return null;
    return can(ResourceCode.Files, ActionCode.Read) ? null : FILES_READ_LOCK_MESSAGE;
}

/** A copy's grants capped to what the user holds, as the server's copy does: a flag the user lacks becomes false. */
export function capStorageGrants(grants: StorageGrants | undefined, can: PermissionCheck): StorageGrants | undefined {
    if (!grants) return grants;
    return {
        read: grants.read && canSetStorageGrant('read', can),
        write: grants.write && canSetStorageGrant('write', can),
        delete: grants.delete && canSetStorageGrant('delete', can),
    };
}

export function capNodeStorageGrants<T extends NodeModel>(node: T, can: PermissionCheck): T {
    if (node.type === NodeType.CLASSIFICATION_TABLE) {
        const table = node as unknown as ClassificationDecisionTableNodeModel;
        return {
            ...node,
            preStorageGrants: capStorageGrants(table.preStorageGrants, can),
            postStorageGrants: capStorageGrants(table.postStorageGrants, can),
        };
    }
    return hasStorageGrantsForNodeType(node.type)
        ? { ...node, storageGrants: capStorageGrants(node.storageGrants, can) }
        : node;
}
