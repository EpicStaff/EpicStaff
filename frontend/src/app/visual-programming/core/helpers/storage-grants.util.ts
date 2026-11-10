import { ActionCode, NodeType, ResourceCode, StorageGrant } from '@shared/models';
import {
    filesPermissionLabel,
    missingStorageGrantActions,
    STORAGE_GRANT_FILES_ACTIONS,
    storageGrantLockMessage,
    storageToggleLockMessage,
} from '@shared/utils';

import {
    ClassificationDecisionTableNodeModel,
    NodeModel,
    PythonNodeModel,
    WebhookTriggerNodeModel,
} from '../models/node.model';
import {
    CdtStorageGrantFields,
    StorageGrantFields,
    StorageGrants,
    StorageGrantSlot,
} from '../models/storage-grants.model';
import { isTriggerNodeType } from './trigger-node-type.util';

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
    NodeType.FILE_EXTRACTOR,
    NodeType.AUDIO_TO_TEXT,
    NodeType.AGENT,
    NodeType.TASK,
    NodeType.CLASSIFICATION_TABLE,
]);

/** Shown on a node whose code gets no file access when a trigger starts the flow. */
export const NO_FILE_ACCESS_TOOLTIP =
    'When a trigger starts this flow, this node gets no access to the flow’s attached files.';

const NO_ACCESS: StorageGrants = { read: false, write: false, delete: false };

/** Whether the user holds a Files action. */
export type PermissionCheck = (resource: ResourceCode, action: ActionCode) => boolean;

export function hasStorageGrantsForNodeType(type: NodeType): boolean {
    return STORAGE_GRANT_NODE_TYPES.has(type);
}

/**
 * The grants a node created in the editor starts with: explicitly none, which the server accepts from any role.
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
 * (an older server, a version snapshot), so a save leaves them out instead of inventing a value.
 */
export function storageGrantsFromDto(
    dto: StorageGrantFields | CdtStorageGrantFields,
    slot: StorageGrantSlot = 'main'
): StorageGrants | undefined {
    const columns = dto as Record<string, boolean | null | undefined>;
    const prefix = columnPrefix(slot);
    const read = columns[`${prefix}read`];
    const write = columns[`${prefix}write`];
    const remove = columns[`${prefix}delete`];
    if (read === undefined && write === undefined && remove === undefined) return undefined;
    return { read: read ?? null, write: write ?? null, delete: remove ?? null };
}

/** The three columns of one slot for a save: all of them as held, or none when the node holds no grants. */
export function storageGrantsToPayload(
    grants: StorageGrants | undefined,
    slot: StorageGrantSlot = 'main'
): Record<string, boolean | null> {
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

export function isStorageGrantConfigured(grants: StorageGrants | undefined): boolean {
    return !!grants && STORAGE_GRANT_KINDS.some((kind) => grants[kind] !== null);
}

export function hasNoStorageAccess(grants: StorageGrants | undefined): boolean {
    return !!grants && STORAGE_GRANT_KINDS.every((kind) => grants[kind] === false);
}

/**
 * The grants after the user flips one box. From "not configured" (or a node that holds none yet) the slot
 * becomes explicit: the touched box takes the value, the other two become false.
 */
export function toggleStorageGrant(
    grants: StorageGrants | undefined,
    kind: StorageGrant,
    value: boolean
): StorageGrants {
    const base: StorageGrants = grants && isStorageGrantConfigured(grants) ? grants : { ...NO_ACCESS };
    return { ...base, [kind]: value };
}

export function canSetStorageGrant(kind: StorageGrant, can: PermissionCheck): boolean {
    return STORAGE_GRANT_FILES_ACTIONS[kind].every((action) => can(ResourceCode.Files, action));
}

/**
 * Whether the user may tick or untick one box of a slot with these grants. Leaving "not configured" makes the
 * other boxes explicit false, so it takes the permissions behind every action; a configured slot takes its own.
 */
export function canEditStorageGrant(
    grants: StorageGrants | undefined,
    kind: StorageGrant,
    can: PermissionCheck
): boolean {
    if (grants && !isStorageGrantConfigured(grants)) {
        return STORAGE_GRANT_KINDS.every((each) => canSetStorageGrant(each, can));
    }
    return canSetStorageGrant(kind, can);
}

/** Shown on every box of a not-configured slot for a user who does not hold every Files permission. */
export const NOT_CONFIGURED_GRANTS_DISABLED_TOOLTIP =
    "Only someone with every Files permission can set file access for a node that isn't configured yet.";

export function storageGrantDisabledTooltip(kind: StorageGrant): string {
    const needed = STORAGE_GRANT_FILES_ACTIONS[kind].map(filesPermissionLabel).join(' and ');
    return `Your role lacks the permission needed to change this: ${needed}.`;
}

/**
 * Whether the slot's code reaches the flow's storage, which is what makes a not-configured slot hold every
 * Files action on the server: a file extractor and an audio transcription always do, Python and webhook code
 * and each classification table slot when its storage switch is on. An agent or task is decided by its tools,
 * which the editor does not resolve, so only the server refuses those.
 */
export function slotInvolvesStorage(node: NodeModel, slot: StorageGrantSlot = 'main'): boolean {
    switch (node.type) {
        case NodeType.FILE_EXTRACTOR:
        case NodeType.AUDIO_TO_TEXT:
            return true;
        case NodeType.PYTHON:
            return (node as PythonNodeModel).data?.use_storage === true;
        case NodeType.WEBHOOK_TRIGGER:
            return (node as WebhookTriggerNodeModel).data?.use_storage === true;
        case NodeType.CLASSIFICATION_TABLE: {
            const table = (node as ClassificationDecisionTableNodeModel).data?.table;
            if (slot === 'pre') return table?.pre_use_storage === true;
            if (slot === 'post') return table?.post_use_storage === true;
            return false;
        }
        default:
            return false;
    }
}

/**
 * The grants a slot holds for locking: the ones it grants when configured; all three when it is not configured
 * and its code reaches storage (the server counts that as every action); none otherwise.
 */
export function heldStorageGrantKinds(grants: StorageGrants | undefined, involvesStorage: boolean): StorageGrant[] {
    if (!grants) return [];
    if (isStorageGrantConfigured(grants)) return STORAGE_GRANT_KINDS.filter((kind) => grants[kind] === true);
    return involvesStorage ? [...STORAGE_GRANT_KINDS] : [];
}

/**
 * The note that locks a slot's code and its steering fields, or `null`: the grants the slot holds include a
 * permission the user's own role lacks. While the user's permissions are not loaded nothing locks, the server decides.
 */
export function storageGrantLockOf(
    grants: StorageGrants | undefined,
    can: PermissionCheck,
    arePermissionsLoaded: () => boolean,
    involvesStorage = false
): string | null {
    if (!grants || !arePermissionsLoaded()) return null;
    const held = heldStorageGrantKinds(grants, involvesStorage);
    const missing = missingStorageGrantActions(held, (action) => can(ResourceCode.Files, action));
    return missing.length ? storageGrantLockMessage('code', missing) : null;
}

/**
 * The note that keeps a storage switch off, or `null`: the slot is not configured, its storage is off, and the
 * user lacks a Files action that turning storage on would make the code hold. Nothing else locks the slot yet.
 */
export function storageToggleLockOf(
    grants: StorageGrants | undefined,
    can: PermissionCheck,
    arePermissionsLoaded: () => boolean,
    involvesStorage: boolean
): string | null {
    if (!grants || isStorageGrantConfigured(grants) || involvesStorage || !arePermissionsLoaded()) return null;
    const missing = missingStorageGrantActions(STORAGE_GRANT_KINDS, (action) => can(ResourceCode.Files, action));
    return missing.length ? storageToggleLockMessage(missing) : null;
}

/**
 * A copy's grants capped to what the user holds, as the server's copy does: a flag the user lacks becomes false.
 * A not-configured slot stays so only for a user holding all three; for anyone else it becomes explicit with the
 * flags they hold.
 */
export function capStorageGrants(grants: StorageGrants | undefined, can: PermissionCheck): StorageGrants | undefined {
    if (!grants) return grants;
    const holds = (kind: StorageGrant) => canSetStorageGrant(kind, can);
    if (!isStorageGrantConfigured(grants)) {
        return STORAGE_GRANT_KINDS.every(holds)
            ? grants
            : { read: holds('read'), write: holds('write'), delete: holds('delete') };
    }
    return {
        read: grants.read === true && holds('read'),
        write: grants.write === true && holds('write'),
        delete: grants.delete === true && holds('delete'),
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

function cdtSlotHasCode(node: ClassificationDecisionTableNodeModel, slot: 'pre' | 'post'): boolean {
    const computation = slot === 'pre' ? node.data?.table?.pre_computation : node.data?.table?.post_computation;
    return !!computation?.code?.trim();
}

/** Whether one of the node's code slots is explicitly set to no file access at all. */
export function hasNoFileAccessSlot(node: NodeModel): boolean {
    if (!hasStorageGrantsForNodeType(node.type)) return false;
    if (node.type === NodeType.CLASSIFICATION_TABLE) {
        const table = node as ClassificationDecisionTableNodeModel;
        return (['pre', 'post'] as const).some(
            (slot) => cdtSlotHasCode(table, slot) && hasNoStorageAccess(getNodeStorageGrants(table, slot))
        );
    }
    return hasNoStorageAccess(getNodeStorageGrants(node));
}

/**
 * The ids of the nodes that get no access to the flow's files when a trigger starts the flow. Empty when the
 * flow has no trigger node: only trigger-started runs apply the grants.
 */
export function nodeIdsWithoutFileAccessWhenTriggered(nodes: readonly NodeModel[]): ReadonlySet<string> {
    if (!nodes.some((node) => isTriggerNodeType(node.type))) return new Set();
    return new Set(nodes.filter(hasNoFileAccessSlot).map((node) => node.id));
}

const FULL_FILE_ACCESS_CONSEQUENCE =
    "code can read, write and delete the flow's files when the flow is started by a trigger. Set its file access in the node panel.";

/** Shown on a node whose file access was never configured: the legacy behaviour gives its code every access. */
export const FULL_FILE_ACCESS_TOOLTIP = `Not configured: this node's ${FULL_FILE_ACCESS_CONSEQUENCE}`;

const CDT_SLOT_NAMES = { pre: 'pre-computation', post: 'post-computation' } as const;

/** The tooltip for a classification table: names the code slot(s) whose file access is not configured. */
export function fullFileAccessTooltipForSlots(slots: readonly ('pre' | 'post')[]): string {
    const names = slots.map((slot) => CDT_SLOT_NAMES[slot]).join(' and ');
    return `Not configured (${names}): this node's ${FULL_FILE_ACCESS_CONSEQUENCE}`;
}

/** The slots of a node whose grants were never configured (all three still null); `main` for a single-slot node. */
export function notConfiguredFileAccessSlots(node: NodeModel): StorageGrantSlot[] {
    if (!hasStorageGrantsForNodeType(node.type)) return [];
    const isNotConfigured = (grants: StorageGrants | undefined): boolean =>
        !!grants && !isStorageGrantConfigured(grants);
    if (node.type === NodeType.CLASSIFICATION_TABLE) {
        const table = node as ClassificationDecisionTableNodeModel;
        return (['pre', 'post'] as const).filter(
            (slot) => isNotConfigured(getNodeStorageGrants(table, slot)) && cdtSlotHasCode(table, slot)
        );
    }
    return isNotConfigured(getNodeStorageGrants(node)) ? ['main'] : [];
}

/**
 * The ids of the nodes whose file access was never configured, so the legacy full access applies when a trigger
 * starts the flow. Empty when the flow has no trigger node.
 */
export function nodeIdsWithFullFileAccessWhenTriggered(nodes: readonly NodeModel[]): ReadonlySet<string> {
    if (!nodes.some((node) => isTriggerNodeType(node.type))) return new Set();
    return new Set(nodes.filter((node) => notConfiguredFileAccessSlots(node).length > 0).map((node) => node.id));
}
