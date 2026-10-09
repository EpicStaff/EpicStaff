import { GetRecycleBinEntryResponse, RecycleBinItem, RecycleBinResourceSourceKey } from '../models/recycle-bin.model';
import {
    newestFirst,
    storageOwnName,
    toRecycleBinDetail,
    toRecycleBinItem,
    toRestoreOutcome,
    toStorageRecycleBinItem,
    UNNAMED_CONTENT,
} from './recycle-bin-mappers.util';

function entry(overrides: Partial<GetRecycleBinEntryResponse> = {}): GetRecycleBinEntryResponse {
    return {
        id: 3,
        name: 'Writer',
        deleted_at: '2026-10-01T10:00:00Z',
        days_left: 6,
        details: [],
        contents: [],
        contents_total: 0,
        ...overrides,
    };
}

describe('recycle bin mappers', () => {
    it('maps a plain entry to a view item', () => {
        expect(toRecycleBinItem('agent', entry())).toEqual({
            key: 'agent-3',
            id: 3,
            source: 'agent',
            name: 'Writer',
            displayName: 'Writer',
            kind: 'Agent',
            deletedAt: new Date('2026-10-01T10:00:00Z'),
            daysLeft: 6,
            details: [],
            contents: [],
            contentsTotal: 0,
        });
    });

    it.each<[RecycleBinResourceSourceKey, string, string]>([
        ['flow', 'Parse', 'python'],
        ['agent', 'Support chat', 'surface'],
        ['surface', 'Parser', 'python_tool'],
        ['collection', 'manual.pdf', 'document'],
        ['python_tool', 'never sent', 'file'],
        ['mcp_tool', 'never sent', 'file'],
    ])('%s: maps its contents and their total', (source, name, kind) => {
        const item = toRecycleBinItem(source, entry({ contents: [{ name, kind }], contents_total: 1 }));
        expect(item.contents).toEqual([{ name, nodeType: kind, key: `${kind}-0` }]);
        expect(item.contentsTotal).toBe(1);
    });

    it('keeps a kind the frontend does not know, so the list matches the total', () => {
        const item = toRecycleBinItem('flow', entry({ contents: [{ name: 'Old', kind: 'crew' }], contents_total: 1 }));
        expect(item.contents).toEqual([{ name: 'Old', nodeType: 'crew', key: 'crew-0' }]);
    });

    it('names a content without a name', () => {
        const item = toRecycleBinItem('flow', entry({ contents: [{ name: '', kind: 'table' }], contents_total: 1 }));
        expect(item.contents[0].name).toBe(UNNAMED_CONTENT);
    });

    it('maps a storage folder with its full path, and its contents as a tree', () => {
        const item = toStorageRecycleBinItem({
            ...entry({ id: 9, name: 'docs/reports/' }),
            item_type: 'folder',
            // In the order a punctuation-blind collation could send them: the subfolder's file first.
            contents: [
                { name: 'sub/b.txt', kind: 'file' },
                { name: 'a.txt', kind: 'file' },
                { name: 'sub/', kind: 'folder' },
                { name: 'sub.md', kind: 'file' },
            ],
            contents_total: 2300,
        });
        expect(item).toMatchObject({ key: 'storage-9', source: 'storage', kind: 'Folder', name: 'docs/reports/' });
        expect(item.contents).toEqual([
            { name: 'a.txt', nodeType: 'file', key: 'a.txt', depth: 0 },
            { name: 'sub/', nodeType: 'folder', key: 'sub/', depth: 0 },
            { name: 'b.txt', nodeType: 'file', key: 'sub/b.txt', depth: 1 },
            { name: 'sub.md', nodeType: 'file', key: 'sub.md', depth: 0 },
        ]);
        expect(item.contentsTotal).toBe(2300);
    });

    it('keeps a notice detail as a notice', () => {
        expect(toRecycleBinDetail({ label: 'Comes back to', value: 'A new docs/ folder', format: 'notice' })).toEqual({
            label: 'Comes back to',
            value: 'A new docs/ folder',
            format: 'notice',
        });
    });

    it('maps a restore response', () => {
        const outcome = toRestoreOutcome('flow', { id: 1, name: 'Report #2', renamed_from: 'Report' });
        expect(outcome).toEqual({ source: 'flow', name: 'Report #2', renamedFrom: 'Report' });
    });

    it('sorts newest first, then higher id first', () => {
        const deletedAt = new Date('2026-10-01T10:00:00Z');
        const older = { id: 20, deletedAt: new Date('2026-09-30T10:00:00Z') } as RecycleBinItem;
        const lowerId = { id: 4, deletedAt } as RecycleBinItem;
        const higherId = { id: 9, deletedAt } as RecycleBinItem;
        const sorted = [older, lowerId, higherId].sort(newestFirst);
        expect(sorted.map((item) => item.id)).toEqual([9, 4, 20]);
    });

    it('maps the details of every source', () => {
        const item = toRecycleBinItem(
            'mcp_tool',
            entry({
                details: [
                    { label: 'Server', value: 'sse', format: 'text' },
                    { label: 'Tool name', value: 'search', format: 'text' },
                ],
            })
        );
        expect(item.details).toEqual([
            { label: 'Server', format: 'text', value: 'sse' },
            { label: 'Tool name', format: 'text', value: 'search' },
        ]);
    });

    it('turns a date detail into a Date and keeps a size as bytes', () => {
        expect(toRecycleBinDetail({ label: 'Created', value: '2026-09-01T08:00:00Z', format: 'date' })).toEqual({
            label: 'Created',
            format: 'date',
            value: new Date('2026-09-01T08:00:00Z'),
        });
        expect(toRecycleBinDetail({ label: 'Size', value: 2048, format: 'size' })).toEqual({
            label: 'Size',
            format: 'size',
            value: 2048,
        });
    });

    it('shows a value that does not parse in its format as text', () => {
        expect(toRecycleBinDetail({ label: 'Created', value: 'soon', format: 'date' })).toEqual({
            label: 'Created',
            format: 'text',
            value: 'soon',
        });
        expect(toRecycleBinDetail({ label: 'Size', value: 'big', format: 'size' })).toEqual({
            label: 'Size',
            format: 'text',
            value: 'big',
        });
    });

    it('maps the details of a storage file', () => {
        const item = toStorageRecycleBinItem({
            ...entry({ id: 12, name: 'docs/a.txt' }),
            item_type: 'file',
            details: [
                { label: 'Size', value: 1536, format: 'size' },
                { label: 'Type', value: 'TXT', format: 'text' },
            ],
        });
        expect(item.details.map((detail) => detail.label)).toEqual(['Size', 'Type']);
    });

    it('maps an empty detail to an empty line, whatever its format', () => {
        expect(toRecycleBinDetail({ label: 'Created', value: null, format: 'date' })).toEqual({
            label: 'Created',
            format: 'empty',
            value: null,
        });
    });

    it.each([
        ['docs/reports/report.pdf', 'report.pdf'],
        ['docs/old/', 'old/'],
        ['root.txt', 'root.txt'],
    ])('shows the storage row %s by its own name %s', (path, ownName) => {
        expect(storageOwnName(path)).toBe(ownName);
        const item = toStorageRecycleBinItem({
            ...entry({ id: 1, name: path }),
            item_type: path.endsWith('/') ? 'folder' : 'file',
        });
        expect(item.displayName).toBe(ownName);
        expect(item.name).toBe(path);
    });

    it('shows every other source by its full name', () => {
        expect(toRecycleBinItem('flow', entry({ name: 'Reports/Daily' })).displayName).toBe('Reports/Daily');
    });

    it('maps a key-value table with its key count and no key names', () => {
        const item = toRecycleBinItem('key_value_table', entry({ id: 6, name: 'Prices', contents_total: 2 }));
        expect(item).toMatchObject({ key: 'key_value_table-6', source: 'key_value_table', kind: 'Key-value table' });
        expect(item.contentsTotal).toBe(2);
        expect(item.contents).toEqual([]);
    });
});
