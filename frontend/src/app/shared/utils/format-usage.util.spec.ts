import { formatSmallCostUsd } from './format-usage.util';

describe('formatSmallCostUsd', () => {
    it('formats a cent or more like formatCostUsd', () => {
        expect(formatSmallCostUsd(0.5)).toBe('$0.50');
        expect(formatSmallCostUsd(0.01)).toBe('$0.01');
    });

    it('keeps 2 significant digits below a cent', () => {
        expect(formatSmallCostUsd(0.00123)).toBe('$0.0012');
        expect(formatSmallCostUsd(0.000034)).toBe('$0.000034');
    });

    it('returns a floor label below one millionth of a dollar', () => {
        expect(formatSmallCostUsd(0.0000001)).toBe('< $0.000001');
        expect(formatSmallCostUsd(0.000001)).toBe('$0.0000010');
    });

    it('returns an empty string for zero or negative costs', () => {
        expect(formatSmallCostUsd(0)).toBe('');
        expect(formatSmallCostUsd(-1)).toBe('');
    });
});
