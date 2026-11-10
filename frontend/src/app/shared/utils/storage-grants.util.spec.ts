import { ActionCode } from '@shared/models';

import { missingStorageGrantActions, storageGrantLockMessage } from './storage-grants.util';

function holding(...actions: ActionCode[]): (action: ActionCode) => boolean {
    return (action) => actions.includes(action);
}

describe('missingStorageGrantActions', () => {
    it.each([
        { grants: ['read' as const], held: [], missing: [ActionCode.Read] },
        { grants: ['write' as const], held: [ActionCode.Create], missing: [ActionCode.Update] },
        {
            grants: ['delete' as const, 'write' as const, 'read' as const],
            held: [],
            missing: [ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete],
        },
        {
            grants: ['read' as const, 'write' as const],
            held: [ActionCode.Read, ActionCode.Create, ActionCode.Update],
            missing: [],
        },
        { grants: [], held: [], missing: [] },
    ])('grants $grants held $held lack $missing', ({ grants, held, missing }) => {
        expect(missingStorageGrantActions(grants, holding(...held))).toEqual(missing);
    });
});

describe('storageGrantLockMessage', () => {
    it('lists each missing permission as a role shows it', () => {
        expect(storageGrantLockMessage('code', [ActionCode.Read, ActionCode.Update])).toBe(
            "This code runs with Files: Read, Files: Update, which you don't have. Contact an admin to change it."
        );
    });

    it('names the flows for a shared tool', () => {
        expect(storageGrantLockMessage('tool', [ActionCode.Delete], ['Orders', 'Billing'])).toBe(
            "This tool runs with Files: Delete in flows Orders, Billing, which you don't have. Contact an admin to change it."
        );
    });
});
