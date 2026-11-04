import { ActionCode, StorageGrant } from '@shared/models';

/** The Files permissions each storage grant stands for: what a role needs to set, clear or edit code that has it. */
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

/**
 * The note shown where something may not be edited because it runs with Files permissions the user lacks.
 * `subject` is what runs ("code", "tool"); `flowNames` names the flows that grant it, when it is shared.
 */
export function storageGrantLockMessage(
    subject: string,
    missing: readonly ActionCode[],
    flowNames: readonly string[] = []
): string {
    const permissions = missing.map(filesPermissionLabel).join(', ');
    const where = flowNames.length ? ` in flows ${flowNames.join(', ')}` : '';
    return `This ${subject} runs with ${permissions}${where}, which you don't have. Contact an admin to change it.`;
}
