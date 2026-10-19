import { PURGED_NAME_MAX_LENGTH, recycleBinPurgeMessage } from './recycle-bin-purge.utils';

describe('recycleBinPurgeMessage', () => {
    it('returns null when nothing was purged', () => {
        expect(recycleBinPurgeMessage([])).toBeNull();
    });

    it('names the single purged file', () => {
        expect(recycleBinPurgeMessage([{ name: 'docs/a.txt', size: 7 }])).toBe(
            'Storage was full, so "docs/a.txt" was permanently deleted from the recycle bin.'
        );
    });

    it('names the single purged folder', () => {
        expect(recycleBinPurgeMessage([{ name: 'old/', size: 7 }])).toBe(
            'Storage was full, so "old/" was permanently deleted from the recycle bin.'
        );
    });

    it('speaks of the oldest item when the single entry has no readable name', () => {
        expect(recycleBinPurgeMessage([{ name: null, size: 7 }])).toBe(
            'Storage was full, so the oldest item in the recycle bin was permanently deleted.'
        );
    });

    it('counts several purged entries', () => {
        const entries = [
            { name: 'a.txt', size: 1 },
            { name: 'b.txt', size: 2 },
            { name: 'old/', size: 3 },
        ];
        expect(recycleBinPurgeMessage(entries)).toBe(
            'Storage was full, so the 3 oldest items in the recycle bin were permanently deleted.'
        );
    });

    it('counts several entries without readable names', () => {
        const entries = [
            { name: null, size: 1 },
            { name: null, size: 2 },
        ];
        expect(recycleBinPurgeMessage(entries)).toBe(
            'Storage was full, so the 2 oldest items in the recycle bin were permanently deleted.'
        );
    });

    it('cuts a long path from the start so the toast keeps the file name', () => {
        const name = `${'deeply/nested/folder/'.repeat(5)}report.pdf`;
        const message = recycleBinPurgeMessage([{ name, size: 1 }]);
        const quoted = message?.match(/"(.*)"/)?.[1] ?? '';

        expect(quoted).toHaveLength(PURGED_NAME_MAX_LENGTH);
        expect(quoted.startsWith('…')).toBe(true);
        expect(quoted.endsWith('/report.pdf')).toBe(true);
    });

    it('never splits an astral character when cutting a long path', () => {
        const name = `${'😀'.repeat(PURGED_NAME_MAX_LENGTH + 5)}.txt`;
        const message = recycleBinPurgeMessage([{ name, size: 1 }]);
        const quoted = message?.match(/"(.*)"/)?.[1] ?? '';
        const characters = Array.from(quoted);

        expect(characters).toHaveLength(PURGED_NAME_MAX_LENGTH);
        expect(characters[0]).toBe('…');
        expect(characters.slice(1, -4).every((character) => character === '😀')).toBe(true);
        expect(quoted.endsWith('.txt')).toBe(true);
    });
});
