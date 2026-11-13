import { ActionCode, NodeType, ResourceCode } from '@shared/models';

import { ClassificationDecisionTableNodeModel, NodeModel } from '../models/node.model';
import { StorageGrants } from '../models/storage-grants.model';
import {
    canEditStorageGrant,
    canSetStorageGrant,
    capNodeStorageGrants,
    capStorageGrants,
    FILES_READ_LOCK_MESSAGE,
    filesReadLockOf,
    newNodeStorageGrants,
    nodeIdsWithoutFileAccess,
    PermissionCheck,
    storageGrantLockOf,
    storageGrantsFromDto,
    toggleStorageGrant,
} from './storage-grants.util';

const NONE: StorageGrants = { read: false, write: false, delete: false };
const ALL: StorageGrants = { read: true, write: true, delete: true };

/** A role that holds exactly these Files actions. */
function roleWith(...actions: ActionCode[]): PermissionCheck {
    return (resource, action) => resource === ResourceCode.Files && actions.includes(action);
}

const EVERY_ACTION = roleWith(ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete);

function node(id: string, type: NodeType, extra: Partial<NodeModel> = {}): NodeModel {
    return { id, type, ...extra } as NodeModel;
}

describe('toggleStorageGrant', () => {
    it('starts a node that holds none yet from every box false', () => {
        expect(toggleStorageGrant(undefined, 'read', true)).toEqual({ read: true, write: false, delete: false });
    });

    it('changes only the touched box', () => {
        expect(toggleStorageGrant({ read: true, write: false, delete: true }, 'delete', false)).toEqual({
            read: true,
            write: false,
            delete: false,
        });
    });
});

describe('which grants a role may set', () => {
    it.each([
        { grant: 'read' as const, actions: [ActionCode.Read], allowed: true },
        { grant: 'read' as const, actions: [ActionCode.Create], allowed: false },
        { grant: 'write' as const, actions: [ActionCode.Create, ActionCode.Update], allowed: true },
        { grant: 'write' as const, actions: [ActionCode.Create], allowed: false },
        { grant: 'write' as const, actions: [ActionCode.Update], allowed: false },
        { grant: 'delete' as const, actions: [ActionCode.Delete], allowed: true },
        { grant: 'delete' as const, actions: [ActionCode.Read, ActionCode.Update], allowed: false },
    ])('$grant with $actions is allowed: $allowed', ({ grant, actions, allowed }) => {
        expect(canSetStorageGrant(grant, roleWith(...actions))).toBe(allowed);
    });
});

describe('canEditStorageGrant', () => {
    const readOnly = roleWith(ActionCode.Read);

    it('always lets a ticked box be unticked, whatever the role holds', () => {
        expect(canEditStorageGrant(ALL, 'delete', roleWith())).toBe(true);
        expect(canEditStorageGrant({ read: false, write: false, delete: true }, 'delete', readOnly)).toBe(true);
    });

    it('lets an unticked box be ticked only with the permission behind it', () => {
        expect(canEditStorageGrant(NONE, 'read', readOnly)).toBe(true);
        expect(canEditStorageGrant(NONE, 'delete', readOnly)).toBe(false);
        expect(canEditStorageGrant(undefined, 'delete', readOnly)).toBe(false);
    });
});

describe('storage grant lock', () => {
    const loaded = () => true;

    it('names the ticked boxes permissions the role lacks, in order', () => {
        expect(storageGrantLockOf(ALL, roleWith(ActionCode.Read, ActionCode.Update), loaded)).toBe(
            "This code runs with Files: Create, Files: Delete, which you don't have. You can only untick its file access; contact an admin to change anything else."
        );
    });

    it('does not lock on boxes that are unticked, or on a node with no grants', () => {
        expect(storageGrantLockOf(NONE, roleWith(), loaded)).toBeNull();
        expect(storageGrantLockOf(undefined, roleWith(), loaded)).toBeNull();
    });

    it('does not lock a role that covers every ticked box', () => {
        const role = roleWith(ActionCode.Read, ActionCode.Create, ActionCode.Update);

        expect(storageGrantLockOf({ read: true, write: true, delete: false }, role, loaded)).toBeNull();
    });

    it('does not lock while the permissions are not loaded yet', () => {
        expect(storageGrantLockOf(ALL, roleWith(), () => false)).toBeNull();
    });
});

describe('filesReadLockOf', () => {
    const loaded = () => true;

    it.each([NodeType.FILE_EXTRACTOR, NodeType.AUDIO_TO_TEXT])('locks %s for a role without Files:Read', (type) => {
        expect(filesReadLockOf(type, roleWith(ActionCode.Create), loaded)).toBe(FILES_READ_LOCK_MESSAGE);
    });

    it.each([NodeType.FILE_EXTRACTOR, NodeType.AUDIO_TO_TEXT])(
        'does not lock %s for a role with Files:Read',
        (type) => {
            expect(filesReadLockOf(type, roleWith(ActionCode.Read), loaded)).toBeNull();
        }
    );

    it.each([NodeType.PYTHON, NodeType.AGENT, NodeType.CLASSIFICATION_TABLE])(
        'never locks %s, which does not read the files by itself',
        (type) => {
            expect(filesReadLockOf(type, roleWith(), loaded)).toBeNull();
        }
    );

    it('does not lock while the permissions are not loaded yet', () => {
        expect(filesReadLockOf(NodeType.FILE_EXTRACTOR, roleWith(), () => false)).toBeNull();
    });
});

describe('capStorageGrants', () => {
    it('turns off the flags the user lacks and keeps the ones they hold', () => {
        expect(capStorageGrants(ALL, roleWith(ActionCode.Read, ActionCode.Delete))).toEqual({
            read: true,
            write: false,
            delete: true,
        });
    });

    it('never turns a flag on', () => {
        expect(capStorageGrants({ read: false, write: true, delete: false }, EVERY_ACTION)).toEqual({
            read: false,
            write: true,
            delete: false,
        });
    });

    it('leaves absent grants absent', () => {
        expect(capStorageGrants(undefined, roleWith())).toBeUndefined();
    });
});

describe('capNodeStorageGrants', () => {
    it('caps both slots of a classification table independently', () => {
        const table = node('cdt', NodeType.CLASSIFICATION_TABLE, {
            preStorageGrants: ALL,
            postStorageGrants: { read: true, write: false, delete: false },
        } as Partial<NodeModel>);

        const capped = capNodeStorageGrants(table, roleWith(ActionCode.Read)) as ClassificationDecisionTableNodeModel;

        expect(capped.preStorageGrants).toEqual({ read: true, write: false, delete: false });
        expect(capped.postStorageGrants).toEqual({ read: true, write: false, delete: false });
    });

    it('leaves a node type without grants as it is', () => {
        const task = node('task', NodeType.TASK);

        expect(capNodeStorageGrants(task, roleWith())).toBe(task);
    });
});

describe('newNodeStorageGrants', () => {
    it('starts a code node with every box false', () => {
        expect(newNodeStorageGrants(NodeType.PYTHON)).toEqual({ storageGrants: NONE });
    });

    it('starts a classification table with every box false in both slots', () => {
        expect(newNodeStorageGrants(NodeType.CLASSIFICATION_TABLE)).toEqual({
            preStorageGrants: NONE,
            postStorageGrants: NONE,
        });
    });

    it.each([NodeType.END, NodeType.AGENT, NodeType.TASK, NodeType.FILE_EXTRACTOR, NodeType.AUDIO_TO_TEXT])(
        'gives %s no grants',
        (type) => {
            expect(newNodeStorageGrants(type)).toEqual({});
        }
    );
});

describe('storageGrantsFromDto', () => {
    it('reads the three columns of a slot', () => {
        expect(
            storageGrantsFromDto({ storage_grant_read: true, storage_grant_write: false, storage_grant_delete: true })
        ).toEqual({ read: true, write: false, delete: true });
    });

    it('reads the pre slot of a classification table from its prefixed columns', () => {
        expect(
            storageGrantsFromDto(
                { pre_storage_grant_read: false, pre_storage_grant_write: true, pre_storage_grant_delete: false },
                'pre'
            )
        ).toEqual({ read: false, write: true, delete: false });
    });

    it('returns nothing when the server sent none of the columns', () => {
        expect(storageGrantsFromDto({})).toBeUndefined();
    });
});

describe('nodes flagged as having no file access', () => {
    const withData = (type: NodeType, data: object, extra: Partial<NodeModel> = {}) =>
        node('n', type, { data, ...extra } as Partial<NodeModel>);

    it('flags a python node that uses storage with every box false, with no trigger needed', () => {
        const python = withData(NodeType.PYTHON, { use_storage: true }, { id: 'py', storageGrants: NONE });

        expect([...nodeIdsWithoutFileAccess([python])]).toEqual(['py']);
    });

    it('does not flag a node that does not use storage, or has a box ticked', () => {
        const nodes = [
            withData(NodeType.PYTHON, { use_storage: false }, { id: 'unused', storageGrants: NONE }),
            withData(NodeType.WEBHOOK_TRIGGER, { use_storage: true }, { id: 'some', storageGrants: ALL }),
            withData(NodeType.PYTHON, { use_storage: true }, { id: 'absent' }),
        ];

        expect(nodeIdsWithoutFileAccess(nodes).size).toBe(0);
    });

    it('ignores node types that have no granted code', () => {
        const end = node('end', NodeType.END, { storageGrants: NONE });

        expect(nodeIdsWithoutFileAccess([end]).size).toBe(0);
    });

    it('flags a classification table by the slot that uses storage, not by one that does not', () => {
        const table = (preUsesStorage: boolean, postUsesStorage: boolean): ClassificationDecisionTableNodeModel =>
            ({
                id: 'cdt',
                type: NodeType.CLASSIFICATION_TABLE,
                data: { table: { pre_use_storage: preUsesStorage, post_use_storage: postUsesStorage } },
                preStorageGrants: NONE,
                postStorageGrants: ALL,
            }) as unknown as ClassificationDecisionTableNodeModel;

        expect(nodeIdsWithoutFileAccess([table(true, false)]).has('cdt')).toBe(true);
        expect(nodeIdsWithoutFileAccess([table(false, true)]).has('cdt')).toBe(false);
    });
});
