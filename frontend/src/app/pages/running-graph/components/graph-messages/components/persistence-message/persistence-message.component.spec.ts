import { ComponentFixture, TestBed } from '@angular/core/testing';

import {
    GraphMessage,
    MessageType,
    PersistenceMessageData,
    PersistenceMessageEntry,
} from '../../../../models/graph-session-message.model';
import { PersistenceMessageComponent } from './persistence-message.component';

function entry(overrides: Partial<PersistenceMessageEntry>): PersistenceMessageEntry {
    return {
        key: 'key',
        path: null,
        found: null,
        created: null,
        value_preview: null,
        truncated: false,
        ...overrides,
    };
}

type RenderData = Omit<PersistenceMessageData, 'message_type' | 'table_id' | 'table_name'>;

function createFixture(data: RenderData): ComponentFixture<PersistenceMessageComponent> {
    const message: GraphMessage = {
        id: 1,
        session: 1,
        name: 'persist',
        execution_order: 1,
        created_at: '2026-09-26T00:00:00Z',
        metadata: {},
        message_data: { ...data, table_id: 7, table_name: 'profiles', message_type: MessageType.PERSISTENCE },
    };
    const fixture = TestBed.createComponent(PersistenceMessageComponent);
    fixture.componentRef.setInput('message', message);
    fixture.detectChanges();
    return fixture;
}

function render(data: RenderData): HTMLElement {
    return createFixture(data).nativeElement as HTMLElement;
}

function text(element: HTMLElement, selector: string): string {
    return element.querySelector(selector)?.textContent?.trim() ?? '';
}

function chips(element: HTMLElement): { label: string; neutral: boolean }[] {
    return Array.from(element.querySelectorAll('.chip')).map((chip) => ({
        label: chip.textContent?.trim() ?? '',
        neutral: chip.classList.contains('chip--neutral'),
    }));
}

function tokens(preview: Element): [string, string][] {
    return Array.from(preview.querySelectorAll('span')).map((span) => [span.className, span.textContent ?? '']);
}

function iconHref(element: HTMLElement): string | null {
    return element.querySelector('.icon-container use')?.getAttribute('href') ?? null;
}

function mappings(element: HTMLElement): string[] {
    return Array.from(element.querySelectorAll('.entry__mapping')).map((mapping) =>
        Array.from(mapping.querySelectorAll('.entry__target, .arrow, .entry__source'))
            .map((part) => part.textContent?.trim())
            .join(' ')
    );
}

describe('PersistenceMessageComponent', () => {
    it('summarises a read with found and not-found counts', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [
                entry({ key: 'a', path: 'variables.a', found: true, value_preview: '1' }),
                entry({ key: 'b', path: 'variables.b', found: false }),
            ],
        });

        expect(text(element, '.title')).toBe('Read 2 keys from table profiles');
        expect(chips(element)).toEqual([
            { label: '1 found', neutral: false },
            { label: '1 not found', neutral: true },
        ]);
        expect(mappings(element)).toEqual(['variables.a ← a', 'variables.b ← b']);
        const rows = element.querySelectorAll('.entry');
        expect(text(rows[0] as HTMLElement, '.preview')).toBe('1');
        expect(rows[0].querySelector('.not-found')).toBeNull();
        expect(text(rows[1] as HTMLElement, '.not-found')).toBe('not found');
        expect(rows[1].querySelector('.preview')).toBeNull();
    });

    it('uses the singular for one key and hides a zero secondary chip', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value_preview: '1' })],
        });

        expect(text(element, '.title')).toBe('Read 1 key from table profiles');
        expect(chips(element)).toEqual([{ label: '1 found', neutral: false }]);
    });

    it('summarises a write with created and updated counts and tags', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'a', path: 'variables.a|0', created: true, value_preview: '0' }),
                entry({ key: 'b', path: 'variables.b', created: false, value_preview: '"x"' }),
                entry({ key: 'c', path: 'variables.c', created: false, value_preview: '"y"' }),
            ],
        });

        expect(text(element, '.title')).toBe('Wrote 3 keys to table profiles');
        expect(chips(element)).toEqual([
            { label: '1 created', neutral: false },
            { label: '2 updated', neutral: true },
        ]);
        expect(mappings(element)).toEqual(['a ← variables.a|0', 'b ← variables.b', 'c ← variables.c']);
        expect(Array.from(element.querySelectorAll('.tag')).map((tag) => tag.textContent?.trim())).toEqual([
            'created',
            'updated',
            'updated',
        ]);
    });

    it('ends truncated previews with an ellipsis', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'long', path: 'variables.long', created: true, value_preview: '"abc', truncated: true }),
                entry({ key: 'short', path: 'variables.short', created: true, value_preview: '"ab"' }),
            ],
        });

        const previews = Array.from(element.querySelectorAll('.preview')).map((preview) => preview.textContent);
        expect(previews).toEqual(['"abc…', '"ab"']);
    });

    it('highlights a truncated object preview token by token and keeps the ellipsis', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [
                entry({
                    key: 'k',
                    path: 'variables.k',
                    found: true,
                    value_preview: '{"name": "Ann", "tags": ["a\\', // cut mid-escape inside an unclosed array
                    truncated: true,
                }),
            ],
        });

        const preview = element.querySelector('.preview') as Element;
        expect(preview.textContent).toBe('{"name": "Ann", "tags": ["a\\…');
        expect(tokens(preview)).toEqual([
            ['json-punctuation', '{'],
            ['json-key', '"name"'],
            ['json-punctuation', ':'],
            ['json-plain', ' '],
            ['json-string', '"Ann"'],
            ['json-punctuation', ','],
            ['json-plain', ' '],
            ['json-key', '"tags"'],
            ['json-punctuation', ':'],
            ['json-plain', ' '],
            ['json-punctuation', '['],
            ['json-string', '"a\\'],
            ['json-plain', '…'],
        ]);
    });

    it('keeps escaped quotes and backslashes inside their key and string tokens', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'k', path: 'variables.k', found: true, value_preview: '{"a\\"b": "c\\\\"}' })],
        });

        expect(tokens(element.querySelector('.preview') as Element)).toEqual([
            ['json-punctuation', '{'],
            ['json-key', '"a\\"b"'],
            ['json-punctuation', ':'],
            ['json-plain', ' '],
            ['json-string', '"c\\\\"'],
            ['json-punctuation', '}'],
        ]);
    });

    it('highlights plain scalar previews', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'a', path: 'variables.a', value_preview: '"x"' }),
                entry({ key: 'b', path: 'variables.b', value_preview: '-1.5e3' }),
                entry({ key: 'c', path: 'variables.c', value_preview: 'true' }),
                entry({ key: 'd', path: 'variables.d', value_preview: 'null' }),
                entry({ key: 'e', path: 'variables.e', value_preview: 'NaN' }),
            ],
        });

        expect(Array.from(element.querySelectorAll('.preview')).map(tokens)).toEqual([
            [['json-string', '"x"']],
            [['json-number', '-1.5e3']],
            [['json-boolean', 'true']],
            [['json-null', 'null']],
            [['json-plain', 'NaN']],
        ]);
    });

    it('colours table keys and state paths by kind, whichever side of the arrow they are on', () => {
        const kinds = (element: HTMLElement): string[] =>
            Array.from(element.querySelectorAll('.entry__target, .entry__source')).map((part) =>
                part.classList.contains('entry__key') ? `key:${part.textContent}` : `path:${part.textContent}`
            );
        const read = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value_preview: '1' })],
        });
        const write = render({
            mode: 'write',
            deleted_count: null,
            entries: [entry({ key: 'b', path: 'variables.b', created: true, value_preview: '1' })],
        });

        expect(kinds(read)).toEqual(['path:variables.a', 'key:a']);
        expect(kinds(write)).toEqual(['key:b', 'path:variables.b']);
        expect(read.querySelectorAll('.entry__path.entry__key').length).toBe(0);
    });

    it('uses the download / upload-outline / trash icon per mode', () => {
        const icon = (mode: PersistenceMessageData['mode']): string | null =>
            iconHref(render({ mode, deleted_count: mode === 'delete' ? 0 : null, entries: [] }));

        expect([icon('read'), icon('write'), icon('delete')]).toEqual([
            '#icon-download',
            '#icon-upload-outline',
            '#icon-trash',
        ]);
    });

    it('summarises a delete with a neutral "N of M" chip and a missing-keys note', () => {
        const element = render({
            mode: 'delete',
            deleted_count: 1,
            entries: [entry({ key: 'a' }), entry({ key: 'b' }), entry({ key: 'c' })],
        });

        expect(text(element, '.title')).toBe('Removed 1 key from table profiles');
        expect(chips(element)).toEqual([{ label: '1 of 3', neutral: true }]);
        expect(text(element, '.muted-note')).toBe('2 keys were not in the table');
        expect(mappings(element)).toEqual(['a', 'b', 'c']);
        expect(element.querySelector('.arrow, .preview, .tag')).toBeNull();
        expect(element.querySelector('[class*="error"], [class*="danger"], [class*="failed"]')).toBeNull();
    });

    it('reports a delete that removed nothing without looking like an error', () => {
        const element = render({
            mode: 'delete',
            deleted_count: 0,
            entries: [entry({ key: 'a' })],
        });

        expect(text(element, '.title')).toBe('No keys removed from table profiles');
        expect(chips(element)).toEqual([{ label: '0 of 1', neutral: true }]);
        expect(text(element, '.muted-note')).toBe('1 key was not in the table');
        expect(element.querySelector('[class*="error"], [class*="danger"], [class*="failed"]')).toBeNull();
    });

    it('omits the missing-keys note when every requested key was removed', () => {
        const element = render({
            mode: 'delete',
            deleted_count: 2,
            entries: [entry({ key: 'a' }), entry({ key: 'b' })],
        });

        expect(text(element, '.title')).toBe('Removed 2 keys from table profiles');
        expect(element.querySelector('.muted-note')).toBeNull();
    });

    it('starts collapsed with the keys section hidden, and expands on header click', () => {
        const fixture = createFixture({ mode: 'delete', deleted_count: 1, entries: [entry({ key: 'a' })] });
        const element = fixture.nativeElement as HTMLElement;
        const header = element.querySelector<HTMLButtonElement>('.persistence-header');
        const card = element.querySelector('.persistence-container > .collapsible-content');

        expect(card?.classList.contains('expanded')).toBe(false);
        expect(header?.getAttribute('aria-expanded')).toBe('false');
        expect(card?.contains(element.querySelector('.entry'))).toBe(true);

        header?.click();
        fixture.detectChanges();
        expect(card?.classList.contains('expanded')).toBe(true);
        expect(header?.getAttribute('aria-expanded')).toBe('true');
        expect(element.querySelector('.keys-collapsible')?.classList.contains('expanded')).toBe(true);
    });

    it('toggles the keys section independently of the card', () => {
        const fixture = createFixture({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value_preview: '1' })],
        });
        const element = fixture.nativeElement as HTMLElement;
        element.querySelector<HTMLButtonElement>('.persistence-header')?.click();
        fixture.detectChanges();
        const heading = element.querySelector<HTMLButtonElement>('.section-heading');

        expect(heading?.textContent?.trim()).toBe('Keys');
        expect(heading?.getAttribute('aria-expanded')).toBe('true');
        heading?.click();
        fixture.detectChanges();
        expect(element.querySelector('.keys-collapsible')?.classList.contains('expanded')).toBe(false);
        expect(heading?.getAttribute('aria-expanded')).toBe('false');
        expect(
            element.querySelector('.persistence-container > .collapsible-content')?.classList.contains('expanded')
        ).toBe(true);
    });
    it('shows only the key for a read row without a target path', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'orphan', path: null, found: true, value_preview: '1' })],
        });

        expect(mappings(element)).toEqual(['orphan']);
        expect(element.querySelector('.arrow')).toBeNull();
    });

    it('colours the table name in the title', () => {
        const element = render({ mode: 'read', deleted_count: null, entries: [entry({ path: 'variables.a' })] });

        expect(text(element, '.title .table-name')).toBe('profiles');
    });

    it('omits the keys section when there are no entries', () => {
        const element = render({ mode: 'read', deleted_count: null, entries: [] });

        expect(element.querySelector('.keys-container')).toBeNull();
        expect(element.querySelector('.section-heading')).toBeNull();
    });
});
