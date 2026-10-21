import { recycleBinNotice } from './recycle-bin-notice.util';

describe('recycleBinNotice', () => {
    it('names the retention time for one item', () => {
        expect(recycleBinNotice(7)).toBe('It moves to the recycle bin, where you can restore it for 7 days.');
    });

    it('uses the singular for one day', () => {
        expect(recycleBinNotice(1)).toBe('It moves to the recycle bin, where you can restore it for 1 day.');
    });

    it('speaks of several items in the plural', () => {
        expect(recycleBinNotice(7, 3)).toBe('They move to the recycle bin, where you can restore them for 7 days.');
    });

    it('leaves the number out while the retention time is unknown', () => {
        expect(recycleBinNotice(null)).toBe('It moves to the recycle bin, where you can restore it.');
    });
});
