import { fitColumnWidths } from './table-fit-columns';

describe('fitColumnWidths', () => {
    it.each([
        [
            'adds an equal share of the spare space, remainder to the first columns',
            [100, 200, 150],
            452,
            [101, 201, 150],
        ],
        ['rounds content widths up before sharing', [99.2, 100], 300, [150, 150]],
        ['raises a narrow column to the 80px minimum', [10, 100], 280, [130, 150]],
        ['gives a single column all the space', [120], 500, [500]],
        ['keeps exact content widths that already fill the space', [200, 300], 500, [200, 300]],
        ['keeps narrow columns and caps the wide ones equally', [100, 400, 600], 700, [100, 300, 300]],
        ['spreads the rounding remainder over the capped columns', [100, 400, 600], 701, [100, 301, 300]],
        ['caps a single column at the space', [900], 500, [500]],
        ['caps two columns of equal width without keeping either', [300, 300], 500, [250, 250]],
        ['never caps below 80px, so too many columns overflow', [100, 200, 300], 200, [80, 80, 80]],
        ['returns nothing for no columns', [], 500, []],
    ])('%s', (_case, contentWidths, available, expected) => {
        expect(fitColumnWidths(contentWidths, available)).toEqual(expected);
    });
});
