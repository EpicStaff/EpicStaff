import { ActionCode, NodeType, ResourceCode } from '@shared/models';

import { ClassificationDecisionTableNodeModel, NodeModel } from '../models/node.model';
import { StorageGrants } from '../models/storage-grants.model';
import {
    canSetStorageGrant,
    capStorageGrants,
    newNodeStorageGrants,
    nodeIdsWithoutFileAccessWhenTriggered,
    PermissionCheck,
    storageGrantLockOf,
    toggleStorageGrant,
} from './storage-grants.util';

const NOT_CONFIGURED: StorageGrants = { read: null, write: null, delete: null };
const NONE: StorageGrants = { read: false, write: false, delete: false };

/** A role that holds exactly these Files actions. */
function roleWith(...actions: ActionCode[]): PermissionCheck {
    return (resource, action) => resource === ResourceCode.Files && actions.includes(action);
}

function node(id: string, type: NodeType, extra: Partial<NodeModel> = {}): NodeModel {
    return { id, type, ...extra } as NodeModel;
}

describe('toggleStorageGrant', () => {
    it('makes a not-configured slot explicit: the ticked box is true, the other two false', () => {
        expect(toggleStorageGrant(NOT_CONFIGURED, 'write', true)).toEqual({ read: false, write: true, delete: false });
    });

    it('makes the slot of a node the server has not stored explicit the same way', () => {
        expect(toggleStorageGrant(undefined, 'read', true)).toEqual({ read: true, write: false, delete: false });
    });

    it('unticking from not-configured gives all false', () => {
        expect(toggleStorageGrant(NOT_CONFIGURED, 'delete', false)).toEqual(NONE);
    });

    it('changes only the touched box of an explicit slot', () => {
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

describe('storage grant lock', () => {
    const loaded = () => true;

    it('names the granted permissions the role lacks, in order', () => {
        const grants: StorageGrants = { read: true, write: true, delete: true };

        expect(storageGrantLockOf(grants, roleWith(ActionCode.Read, ActionCode.Update), loaded)).toBe(
            "This code runs with Files: Create, Files: Delete, which you don't have. Contact an admin to change it."
        );
    });

    it('does not lock on grants that are off, not configured, or absent', () => {
        const nothing = roleWith();

        expect(storageGrantLockOf(NONE, nothing, loaded)).toBeNull();
        expect(storageGrantLockOf(NOT_CONFIGURED, nothing, loaded)).toBeNull();
        expect(storageGrantLockOf(undefined, nothing, loaded)).toBeNull();
    });

    it('does not lock a role that covers every granted permission', () => {
        const role = roleWith(ActionCode.Read, ActionCode.Create, ActionCode.Update);

        expect(storageGrantLockOf({ read: true, write: true, delete: false }, role, loaded)).toBeNull();
    });

    it('does not lock while the permissions are not loaded yet', () => {
        expect(storageGrantLockOf({ read: true, write: true, delete: true }, roleWith(), () => false)).toBeNull();
    });
});

describe('capStorageGrants', () => {
    const everything = roleWith(ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete);

    it('turns off the flags the user lacks and keeps the ones they hold', () => {
        const grants: StorageGrants = { read: true, write: true, delete: true };

        expect(capStorageGrants(grants, roleWith(ActionCode.Read, ActionCode.Delete))).toEqual({
            read: true,
            write: false,
            delete: true,
        });
    });

    it('never turns a flag on', () => {
        expect(capStorageGrants({ read: false, write: true, delete: false }, everything)).toEqual({
            read: false,
            write: true,
            delete: false,
        });
    });

    it('leaves a not-configured slot alone for a user who holds all three', () => {
        expect(capStorageGrants(NOT_CONFIGURED, everything)).toEqual(NOT_CONFIGURED);
    });

    it('makes a not-configured slot explicit, with the flags the user holds, for anyone else', () => {
        expect(capStorageGrants(NOT_CONFIGURED, roleWith(ActionCode.Read, ActionCode.Create))).toEqual({
            read: true,
            write: false,
            delete: false,
        });
    });

    it('leaves absent grants absent', () => {
        expect(capStorageGrants(undefined, roleWith())).toBeUndefined();
    });
});

describe('newNodeStorageGrants', () => {
    it('starts a code node with explicitly no access', () => {
        expect(newNodeStorageGrants(NodeType.PYTHON)).toEqual({ storageGrants: NONE });
    });

    it('starts a classification table with no access in both slots', () => {
        expect(newNodeStorageGrants(NodeType.CLASSIFICATION_TABLE)).toEqual({
            preStorageGrants: NONE,
            postStorageGrants: NONE,
        });
    });

    it('gives a node without granted code nothing', () => {
        expect(newNodeStorageGrants(NodeType.END)).toEqual({});
    });
});

describe('nodes flagged as having no file access when triggered', () => {
    const trigger = node('trigger', NodeType.SCHEDULE_TRIGGER);

    it('flags a code node with explicit all-false grants in a flow that has a trigger', () => {
        const python = node('py', NodeType.PYTHON, { storageGrants: NONE });

        expect([...nodeIdsWithoutFileAccessWhenTriggered([trigger, python])]).toEqual(['py']);
    });

    it('does not flag nodes that are not configured, partly granted, or without grants', () => {
        const nodes = [
            trigger,
            node('null', NodeType.PYTHON, { storageGrants: NOT_CONFIGURED }),
            node('some', NodeType.AGENT, { storageGrants: { read: true, write: false, delete: false } }),
            node('none-yet', NodeType.TASK),
        ];

        expect(nodeIdsWithoutFileAccessWhenTriggered(nodes).size).toBe(0);
    });

    it('flags nothing in a flow without a trigger node', () => {
        const python = node('py', NodeType.PYTHON, { storageGrants: NONE });

        expect(nodeIdsWithoutFileAccessWhenTriggered([python]).size).toBe(0);
    });

    it('ignores node types that run no granted code', () => {
        const end = node('end', NodeType.END, { storageGrants: NONE });

        expect(nodeIdsWithoutFileAccessWhenTriggered([trigger, end]).size).toBe(0);
    });

    it('flags a classification table by a slot that has code, not by an empty one', () => {
        const table = (preCode: string, postCode: string): ClassificationDecisionTableNodeModel =>
            ({
                id: 'cdt',
                type: NodeType.CLASSIFICATION_TABLE,
                data: { table: { pre_computation: { code: preCode }, post_computation: { code: postCode } } },
                preStorageGrants: NONE,
                postStorageGrants: { read: true, write: false, delete: false },
            }) as unknown as ClassificationDecisionTableNodeModel;

        expect(nodeIdsWithoutFileAccessWhenTriggered([trigger, table('x = 1', '')]).has('cdt')).toBe(true);
        expect(nodeIdsWithoutFileAccessWhenTriggered([trigger, table('', 'y = 2')]).has('cdt')).toBe(false);
    });
});
