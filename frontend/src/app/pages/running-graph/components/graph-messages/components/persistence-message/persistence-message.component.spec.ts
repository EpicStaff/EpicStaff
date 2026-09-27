import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { CopyButtonComponent } from '@shared/components';

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
        value: null,
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
                entry({ key: 'a', path: 'variables.a', found: true, value: 1 }),
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
        expect(rows[1].querySelector('.preview, app-json-viewer, .truncated-note')).toBeNull();
    });

    it('uses the singular for one key and hides a zero secondary chip', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value: 1 })],
        });

        expect(text(element, '.title')).toBe('Read 1 key from table profiles');
        expect(chips(element)).toEqual([{ label: '1 found', neutral: false }]);
    });

    it('summarises a write with created and updated counts and tags', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'a', path: 'variables.a|0', created: true, value: 0 }),
                entry({ key: 'b', path: 'variables.b', created: false, value: 'x' }),
                entry({ key: 'c', path: 'variables.c', created: false, value: 'y' }),
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

    it('ends a truncated value with an ellipsis and a note that it is partial', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'long', path: 'variables.long', created: true, value: '"abc', truncated: true }),
                entry({ key: 'short', path: 'variables.short', created: true, value: 'ab' }),
            ],
        });

        const rows = element.querySelectorAll('.entry');
        expect(text(rows[0] as HTMLElement, '.preview')).toBe('"abc…');
        expect(text(rows[0] as HTMLElement, '.truncated-note')).toBe(
            'Message size limit reached — first 200 characters shown'
        );
        expect(text(rows[1] as HTMLElement, '.preview')).toBe('"ab"');
        expect(rows[1].querySelector('.truncated-note')).toBeNull();
        expect(element.querySelector('app-json-viewer')).toBeNull();
    });

    it('renders an object value in the JSON viewer, collapsed by default', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [
                entry({
                    key: 'k',
                    path: 'variables.k',
                    found: true,
                    value: { name: 'Ann', address: { city: 'Kyiv' }, tags: ['a', 'b'] },
                }),
            ],
        });

        const viewer = element.querySelector('.entry .value-content app-json-viewer') as HTMLElement;
        expect(Array.from(viewer.querySelectorAll('.segment-key')).map((key) => key.textContent)).toEqual([
            'name',
            'address',
            'tags',
        ]);
        expect(viewer.querySelectorAll('.segment-main.expandable').length).toBe(2);
        expect(viewer.querySelector('.segment-main.expanded, .children')).toBeNull();
        expect(element.querySelector('.entry .preview, .entry .truncated-note')).toBeNull();
    });

    it('expands a nested object in the viewer on click', () => {
        const fixture = createFixture({
            mode: 'write',
            deleted_count: null,
            entries: [entry({ key: 'k', path: 'variables.k', created: true, value: { address: { city: 'Kyiv' } } })],
        });
        const element = fixture.nativeElement as HTMLElement;

        element.querySelector<HTMLElement>('.segment-main.expandable')?.click();
        fixture.detectChanges();

        expect(text(element, '.children .segment-key')).toBe('city');
        expect(text(element, '.children .segment-value')).toBe('"Kyiv"');
    });

    it('renders an array value in the JSON viewer by index', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [entry({ key: 'k', path: 'variables.k', created: true, value: ['a', { b: 1 }] })],
        });

        const viewer = element.querySelector('.value-content app-json-viewer') as HTMLElement;
        expect(Array.from(viewer.querySelectorAll('.segment-key')).map((key) => key.textContent)).toEqual(['0', '1']);
        expect(viewer.querySelectorAll('.segment-main.expandable').length).toBe(1);
    });

    it('shows a found read whose stored value is null as null, not as not found', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value: null })],
        });

        expect(text(element, '.preview')).toBe('null');
        expect(element.querySelector('.not-found')).toBeNull();
    });

    it('copies the full value: pretty JSON for objects and scalars, strings raw, nothing for a truncated prefix', () => {
        const fixture = createFixture({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'a', path: 'variables.a', value: { b: [1] } }),
                entry({ key: 'b', path: 'variables.b', value: 'say "hi"' }),
                entry({ key: 'c', path: 'variables.c', value: 42 }),
                entry({ key: 'd', path: 'variables.d', value: '"cut', truncated: true }),
            ],
        });

        const copyTexts = fixture.debugElement
            .queryAll(By.directive(CopyButtonComponent))
            .map((button) => (button.componentInstance as CopyButtonComponent).text);
        expect(copyTexts).toEqual([JSON.stringify({ b: [1] }, null, 2), 'say "hi"', '42']);
        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.value-content app-copy-button')).not.toBeNull();
    });

    it('renders an empty object or array inline instead of an empty viewer', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'a', path: 'variables.a', value: {} }),
                entry({ key: 'b', path: 'variables.b', value: [] }),
            ],
        });

        expect(element.querySelector('app-json-viewer')).toBeNull();
        expect(Array.from(element.querySelectorAll('.preview')).map((preview) => preview.textContent)).toEqual([
            '{}',
            '[]',
        ]);
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
                    value: '{"name": "Ann", "tags": ["a\\', // cut mid-escape inside an unclosed array
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
            entries: [
                entry({ key: 'k', path: 'variables.k', found: true, value: '{"a\\"b": "c\\\\"}', truncated: true }),
            ],
        });

        expect(tokens(element.querySelector('.preview') as Element)).toEqual([
            ['json-punctuation', '{'],
            ['json-key', '"a\\"b"'],
            ['json-punctuation', ':'],
            ['json-plain', ' '],
            ['json-string', '"c\\\\"'],
            ['json-punctuation', '}'],
            ['json-plain', '…'],
        ]);
    });

    it('highlights scalar values inline, as JSON', () => {
        const element = render({
            mode: 'write',
            deleted_count: null,
            entries: [
                entry({ key: 'a', path: 'variables.a', value: 'say "hi"' }),
                entry({ key: 'b', path: 'variables.b', value: -1.5e-7 }),
                entry({ key: 'c', path: 'variables.c', value: true }),
                entry({ key: 'd', path: 'variables.d', value: null }),
            ],
        });

        expect(Array.from(element.querySelectorAll('.preview')).map(tokens)).toEqual([
            [['json-string', '"say \\"hi\\""']],
            [['json-number', '-1.5e-7']],
            [['json-boolean', 'true']],
            [['json-null', 'null']],
        ]);
        expect(element.querySelector('app-json-viewer, .truncated-note')).toBeNull();
    });

    it('colours table keys and state paths by kind, whichever side of the arrow they are on', () => {
        const kinds = (element: HTMLElement): string[] =>
            Array.from(element.querySelectorAll('.entry__target, .entry__source')).map((part) =>
                part.classList.contains('entry__key') ? `key:${part.textContent}` : `path:${part.textContent}`
            );
        const read = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value: 1 })],
        });
        const write = render({
            mode: 'write',
            deleted_count: null,
            entries: [entry({ key: 'b', path: 'variables.b', created: true, value: 1 })],
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
        expect(element.querySelector('.arrow, .preview, .tag, app-json-viewer, .truncated-note')).toBeNull();
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
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value: 1 })],
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
            entries: [entry({ key: 'orphan', path: null, found: true, value: 1 })],
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
