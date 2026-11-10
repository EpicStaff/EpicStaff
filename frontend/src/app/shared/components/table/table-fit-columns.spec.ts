import { distributeWidths, fitColumnWidths } from './table-fit-columns';

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

    it.each([
        [
            'stops a growing column at the cap and gives its part to the others',
            [400, 100, 100],
            900,
            450,
            [450, 225, 225],
        ],
        ['holds a column whose content is over the cap to the cap', [900, 100], 1000, 500, [500, 500]],
        ['adds up to less than the space once every column is at the cap', [600, 600], 1500, 500, [500, 500]],
        ['caps the widest column when they do not fit', [300, 900], 700, 500, [300, 400]],
        ['shares as without a cap while no column reaches it', [100, 200, 150], 452, 500, [101, 201, 150]],
    ])('with a cap, %s', (_case, contentWidths, available, maxWidth, expected) => {
        expect(fitColumnWidths(contentWidths, available, maxWidth)).toEqual(expected);
    });
});

describe('distributeWidths by fr weight', () => {
    const NO_CAP = Number.POSITIVE_INFINITY;

    // Each column starts from 0, as an `fr` track does.
    it.each([
        ['shares by weight', [100, 80], [2, 1], 600, NO_CAP, [400, 200]],
        ['shares by weight from zero, not from the minimums', [100, 80], [2, 1], 700, NO_CAP, [467, 233]],
        ['keeps a column at its minimum while its share is smaller', [300, 50], [1, 1], 400, NO_CAP, [300, 100]],
        [
            'holds a column at the cap and shares the rest by weight',
            [100, 80, 80],
            [3, 1, 2],
            900,
            400,
            [400, 167, 333],
        ],
        ['gives what a capped column cannot take to the others', [100, 80, 80], [4, 1, 1], 1000, 400, [400, 300, 300]],
        ['keeps a minimum above the cap', [600, 80], [1, 1], 1000, 500, [600, 400]],
        ['uses the minimums when they do not fit, so the columns overflow', [100, 80], [2, 1], 150, NO_CAP, [100, 80]],
        ['adds up to less than the space once every column is at the cap', [100, 100], [1, 1], 1000, 300, [300, 300]],
        ['gives the px lost to rounding to the largest fractions', [0, 0], [1, 2], 100, NO_CAP, [33, 67]],
        ['gives a weight of 0 no share', [100, 80], [0, 1], 500, NO_CAP, [100, 400]],
        ['returns nothing for no columns', [], [], 500, NO_CAP, []],
    ])('%s', (_case, mins, weights, total, maxWidth, expected) => {
        const claims = mins.map((min, index) => ({ base: 0, min, weight: weights[index] }));
        expect(distributeWidths(claims, total, maxWidth)).toEqual(expected);
    });
});
