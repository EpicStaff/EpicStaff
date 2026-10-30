import { RecycleBinItem } from '../models/recycle-bin.model';
import { unlistedContentsCount } from './recycle-bin-rows.util';

function binItem(overrides: Partial<RecycleBinItem>): RecycleBinItem {
    return {
        key: 'agent-1',
        id: 1,
        source: 'agent',
        name: 'Writer',
        displayName: 'Writer',
        kind: 'Agent',
        deletedAt: new Date('2026-10-01T10:00:00Z'),
        daysLeft: 5,
        details: [],
        contents: [],
        hiddenContentsCount: 0,
        contentsTotal: 0,
        ...overrides,
    };
}

describe('unlistedContentsCount', () => {
    it.each([
        ['names past the cap still count, hidden ones do not', 5010, 3, 7],
        ['more hidden than unlisted never goes below zero', 5002, 4, 0],
    ])('at the cap: %s', (_description, contentsTotal, hiddenContentsCount, expected) => {
        const capped = binItem({
            contents: Array.from({ length: 5000 }, (_, index) => ({ name: `f${index}`, nodeType: 'file' })),
            hiddenContentsCount,
            contentsTotal,
        });

        expect(unlistedContentsCount(capped)).toBe(expected);
    });
});
