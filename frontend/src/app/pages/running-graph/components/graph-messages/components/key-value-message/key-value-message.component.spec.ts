import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { CopyButtonComponent } from '@shared/components';

import {
    GraphMessage,
    KeyValueMessageData,
    KeyValueMessageEntry,
    MessageType,
} from '../../../../models/graph-session-message.model';
import { KeyValueMessageComponent } from './key-value-message.component';

function entry(overrides: Partial<KeyValueMessageEntry>): KeyValueMessageEntry {
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

type RenderData = Omit<KeyValueMessageData, 'message_type' | 'table_id' | 'table_name'> & { table_name?: string };

function createFixture(data: RenderData): ComponentFixture<KeyValueMessageComponent> {
    const message: GraphMessage = {
        id: 1,
        session: 1,
        name: 'persist',
        execution_order: 1,
        created_at: '2026-09-26T00:00:00Z',
        metadata: {},
        message_data: { table_name: 'profiles', ...data, table_id: 7, message_type: MessageType.KEY_VALUE },
    };
    const fixture = TestBed.createComponent(KeyValueMessageComponent);
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

describe('KeyValueMessageComponent', () => {
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
        expect(text(rows[0] as HTMLElement, '.value-content app-json-viewer .segment-value')).toBe('1');
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
        expect(text(rows[0] as HTMLElement, '.value-content .preview')).toBe('"abc…');
        expect(rows[0].querySelector('app-json-viewer, app-copy-button')).toBeNull();
        expect(text(rows[0] as HTMLElement, '.truncated-note')).toBe(
            'Message size limit reached — first 200 characters shown'
        );
        expect(text(rows[1] as HTMLElement, 'app-json-viewer .segment-value')).toBe('"ab"');
        expect(rows[1].querySelector('.preview, .truncated-note')).toBeNull();
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

        expect(text(element, '.value-content .segment-type-null .segment-value')).toBe('null');
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
        expect(
            Array.from(element.querySelectorAll('.value-content .preview')).map((preview) => preview.textContent)
        ).toEqual(['{}', '[]']);
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

    it('renders scalar values in the JSON viewer box with a copy button, like objects', () => {
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

        const values = Array.from(element.querySelectorAll('.entry')).map((row) => {
            const segment = row.querySelector('.value-content app-json-viewer .segment');
            return [segment?.className, segment?.querySelector('.segment-value')?.textContent];
        });
        expect(values).toEqual([
            ['segment segment-type-string', '"say "hi""'],
            ['segment segment-type-number', '-1.5e-7'],
            ['segment segment-type-boolean', 'true'],
            ['segment segment-type-null', 'null'],
        ]);
        expect(element.querySelectorAll('.value-content app-copy-button').length).toBe(4);
        expect(element.querySelector('.preview, .truncated-note, .segment-key, .segment-separator')).toBeNull();
        expect(element.textContent).not.toMatch(/\((string|number|boolean|object)\)/);
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

    it('uses the same database icon for every mode', () => {
        const icon = (mode: KeyValueMessageData['mode']): string | null =>
            iconHref(render({ mode, deleted_count: mode === 'delete' ? 0 : null, entries: [] }));

        expect([icon('read'), icon('write'), icon('delete')]).toEqual([
            '#icon-database',
            '#icon-database',
            '#icon-database',
        ]);
    });

    it('colours the left stripe by mode, like the canvas node', () => {
        const stripe = (mode: KeyValueMessageData['mode']): string | undefined =>
            render({ mode, deleted_count: mode === 'delete' ? 0 : null, entries: [] }).querySelector<HTMLElement>(
                '.key-value-container'
            )?.style.borderLeftColor;

        expect([stripe('read'), stripe('write'), stripe('delete')]).toEqual([
            'var(--success-color)',
            'var(--color-status-processing)',
            'var(--color-status-error)',
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

    it('shows the value a delete removed in the JSON viewer, like a read', () => {
        const fixture = createFixture({
            mode: 'delete',
            deleted_count: 1,
            entries: [entry({ key: 'profile_42', found: true, value: { plan: 'pro' } })],
        });
        const element = fixture.nativeElement as HTMLElement;

        expect(text(element, '.title')).toBe('Removed 1 key from table profiles');
        expect(mappings(element)).toEqual(['profile_42']);
        const viewer = element.querySelector('.entry .value-content app-json-viewer') as HTMLElement;
        expect(text(viewer, '.segment-key')).toBe('plan');
        expect(element.querySelector('.not-found, .preview, .truncated-note, .tag, .arrow')).toBeNull();
        const copyTexts = fixture.debugElement
            .queryAll(By.directive(CopyButtonComponent))
            .map((button) => (button.componentInstance as CopyButtonComponent).text);
        expect(copyTexts).toEqual([JSON.stringify({ plan: 'pro' }, null, 2)]);
    });

    it('marks a key a delete did not find "not found", as a read does, without a missing-keys note', () => {
        const element = render({
            mode: 'delete',
            deleted_count: 1,
            entries: [entry({ key: 'a', found: true, value: null }), entry({ key: 'b', found: false, value: null })],
        });

        expect(chips(element)).toEqual([{ label: '1 of 2', neutral: true }]);
        const rows = element.querySelectorAll('.entry');
        // A deleted key that held null shows null, not "not found".
        expect(text(rows[0] as HTMLElement, '.value-content .segment-type-null .segment-value')).toBe('null');
        expect(rows[0].querySelector('.not-found')).toBeNull();
        expect(text(rows[1] as HTMLElement, '.not-found')).toBe('not found');
        expect(rows[1].querySelector('.value-content, .preview, app-json-viewer, .truncated-note')).toBeNull();
        expect(element.querySelector('.muted-note')).toBeNull();
    });

    it('shows a truncated deleted value as a preview with the size-limit note', () => {
        const element = render({
            mode: 'delete',
            deleted_count: 1,
            entries: [entry({ key: 'long', found: true, value: '{"a": "abc', truncated: true })],
        });

        expect(text(element, '.entry .value-content .preview')).toBe('{"a": "abc…');
        expect(element.querySelector('.entry app-json-viewer, .entry app-copy-button')).toBeNull();
        expect(text(element, '.entry .truncated-note')).toBe('Message size limit reached — first 200 characters shown');
    });

    it('still renders an old delete message, with found and value null, as just its keys', () => {
        // Dev data from before deletes reported them: crew sent `found: null` and `value: null`.
        const element = render({
            mode: 'delete',
            deleted_count: 1,
            entries: [entry({ key: 'a', found: null, value: null }), entry({ key: 'b', found: null, value: null })],
        });

        expect(text(element, '.title')).toBe('Removed 1 key from table profiles');
        expect(mappings(element)).toEqual(['a', 'b']);
        expect(element.querySelector('.value-content, .not-found, .truncated-note')).toBeNull();
        expect(text(element, '.muted-note')).toBe('1 key was not in the table');
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

    it('starts collapsed, and shows the entries straight in the content once the header is expanded', () => {
        const fixture = createFixture({
            mode: 'delete',
            deleted_count: 1,
            entries: [entry({ key: 'a' }), entry({ key: 'b' })],
        });
        const element = fixture.nativeElement as HTMLElement;
        const header = element.querySelector<HTMLButtonElement>('.key-value-header');
        const card = element.querySelector('.key-value-container > .collapsible-content');

        expect(card?.classList.contains('expanded')).toBe(false);
        expect(header?.getAttribute('aria-expanded')).toBe('false');

        header?.click();
        fixture.detectChanges();
        expect(card?.classList.contains('expanded')).toBe(true);
        expect(header?.getAttribute('aria-expanded')).toBe('true');
        // No nested collapsible between the card and its entries.
        expect(element.querySelector('.key-value-content > ul.entries > .entry')).not.toBeNull();
        expect(element.querySelector('.key-value-content > .muted-note')).not.toBeNull();
        expect(card?.querySelectorAll('.collapsible-content, .grid-collapsible, [aria-expanded]').length).toBe(0);
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

    it('cuts a long title to one line with an ellipsis and keeps the full table name in its tooltip', () => {
        const longName = 'customer_profiles_'.repeat(12);
        const element = render({ mode: 'read', deleted_count: null, entries: [], table_name: longName });
        const title = element.querySelector('.title') as HTMLElement;
        const style = getComputedStyle(title);

        expect(title.getAttribute('title')).toBe(longName);
        expect(text(element, '.title .table-name')).toBe(longName);
        expect(chips(element)).toEqual([{ label: '0 found', neutral: false }]);
        expect([style.whiteSpace, style.overflow, style.textOverflow]).toEqual(['nowrap', 'hidden', 'ellipsis']);
    });

    it('omits the entry list when there are no entries', () => {
        const element = render({ mode: 'read', deleted_count: null, entries: [] });

        expect(element.querySelector('.entries')).toBeNull();
    });
});
