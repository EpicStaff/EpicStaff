import { selectionState, toggleAll, toggleOne } from './audit-preset-selection.util';

describe('audit preset selection', () => {
    it('reports none, some or all of the listed presets as selected', () => {
        expect(selectionState(new Set(), [1, 2])).toBe('none');
        expect(selectionState(new Set([1]), [1, 2])).toBe('some');
        expect(selectionState(new Set([1, 2]), [1, 2])).toBe('all');
        expect(selectionState(new Set([3]), [])).toBe('none');
    });

    it('selects every listed preset when not all are selected, keeping hidden ones', () => {
        expect([...toggleAll(new Set([1, 9]), [1, 2])].sort()).toEqual([1, 2, 9]);
    });

    it('clears only the listed presets when all of them are selected', () => {
        expect([...toggleAll(new Set([1, 2, 9]), [1, 2])]).toEqual([9]);
    });

    it('toggles a single preset', () => {
        expect([...toggleOne(new Set([1]), 2)].sort()).toEqual([1, 2]);
        expect([...toggleOne(new Set([1, 2]), 2)]).toEqual([1]);
    });
});
