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
        const group = flowsBulkDeleteGroup(noopTarget, [{ id: 1, name: 'Flow 1' }]);

        expect(group.target).toBe(noopTarget);
        expect(group.label).toEqual(FLOW_BULK_DELETE_LABEL);
    });

    it('maps each flow to a bulk-delete item with its id and name', () => {
        const flows = [
            { id: 1, name: 'Flow 1' },
            { id: 2, name: 'Flow 2' },
        ];

        const group = flowsBulkDeleteGroup(noopTarget, flows);

        expect(group.items).toEqual([
            { id: 1, name: 'Flow 1' },
            { id: 2, name: 'Flow 2' },
        ]);
    });

    it('returns an empty items array for an empty flows list', () => {
        const group = flowsBulkDeleteGroup(noopTarget, []);

        expect(group.items).toEqual([]);
    });

    it('ignores extra fields on the flow objects beyond id and name', () => {
        const flows = [{ id: 1, name: 'Flow 1', description: 'extra', tags: ['x'] }];

        const group = flowsBulkDeleteGroup(noopTarget, flows);

        expect(group.items).toEqual([{ id: 1, name: 'Flow 1' }]);
    });
});
