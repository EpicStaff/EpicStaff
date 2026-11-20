import { ActionCode } from '@shared/models';

/** One kind of access a node's code may be granted on the flow's attached files. */
export type StorageGrant = 'read' | 'write' | 'delete';

/** The Files permissions each storage grant stands for: what a role needs to tick it or to edit code that has it ticked. */
export const STORAGE_GRANT_FILES_ACTIONS: Readonly<Record<StorageGrant, readonly ActionCode[]>> = {
    read: [ActionCode.Read],
    write: [ActionCode.Create, ActionCode.Update],
    delete: [ActionCode.Delete],
};

/** The order permissions are listed in, wherever they are shown. */
const FILES_ACTION_ORDER: readonly ActionCode[] = [
    ActionCode.Read,
    ActionCode.Create,
    ActionCode.Update,
    ActionCode.Delete,
];

/** A Files permission as a role shows it, e.g. "Files: Create". */
export function filesPermissionLabel(action: ActionCode): string {
    return `Files: ${action.charAt(0).toUpperCase()}${action.slice(1)}`;
}

/** The Files actions the grants stand for that the role lacks, in Read, Create, Update, Delete order. */
export function missingStorageGrantActions(
    grants: readonly StorageGrant[],
    hasFilesAction: (action: ActionCode) => boolean
): ActionCode[] {
    const required = new Set(grants.flatMap((grant) => STORAGE_GRANT_FILES_ACTIONS[grant]));
    return FILES_ACTION_ORDER.filter((action) => required.has(action) && !hasFilesAction(action));
}
