import { BulkDeleteTarget } from '@shared/models';
import { describe, expect, it } from 'vitest';

import { FLOW_BULK_DELETE_LABEL, flowsBulkDeleteGroup } from './flows-bulk-delete.util';

const noopTarget: BulkDeleteTarget = {
    previewBulkDelete: () => {
        throw new Error('not used in this spec');
    },
    bulkDelete: () => {
        throw new Error('not used in this spec');
    },
    removeFromCache: () => {},
};

describe('flowsBulkDeleteGroup', () => {
    it('uses the given target and the flow label', () => {
        const group = flowsBulkDeleteGroup(noopTarget, [{ id: 1, name: 'Flow 1' }], 7);

        expect(group.target).toBe(noopTarget);
        expect(group.label).toEqual(FLOW_BULK_DELETE_LABEL);
    });

    it('maps each flow to a bulk-delete item with its id and name', () => {
        const flows = [
            { id: 1, name: 'Flow 1' },
            { id: 2, name: 'Flow 2' },
        ];

        const group = flowsBulkDeleteGroup(noopTarget, flows, 7);

        expect(group.items).toEqual([
            { id: 1, name: 'Flow 1' },
            { id: 2, name: 'Flow 2' },
        ]);
    });

    it('marks the group as moving to the recycle bin with the given retention', () => {
        const group = flowsBulkDeleteGroup(noopTarget, [{ id: 1, name: 'Flow 1' }], 30);

        expect(group.recycleBin).toEqual({ retentionDays: 30 });
    });

    it('keeps the recycle-bin marker when the retention is not loaded yet', () => {
        const group = flowsBulkDeleteGroup(noopTarget, [{ id: 1, name: 'Flow 1' }], null);

        expect(group.recycleBin).toEqual({ retentionDays: null });
    });

    it('returns an empty items array for an empty flows list', () => {
        const group = flowsBulkDeleteGroup(noopTarget, [], 7);

        expect(group.items).toEqual([]);
    });

    it('ignores extra fields on the flow objects beyond id and name', () => {
        const flows = [{ id: 1, name: 'Flow 1', description: 'extra', tags: ['x'] }];

        const group = flowsBulkDeleteGroup(noopTarget, flows, 7);

        expect(group.items).toEqual([{ id: 1, name: 'Flow 1' }]);
    });
});
