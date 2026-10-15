import { RECYCLE_BIN_TAB_BY_KEY } from './recycle-bin-tabs.constants';

describe('RECYCLE_BIN_TAB_BY_KEY', () => {
    it('files each tab under its own key, so its route matches the record', () => {
        for (const [key, tab] of Object.entries(RECYCLE_BIN_TAB_BY_KEY)) {
            expect(tab.key).toBe(key);
        }
    });
});
