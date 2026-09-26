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

        expect(text(element, '.title')).toBe('Read 2 keys from profiles');
        expect(chips(element)).toEqual([
            { label: '1 found', neutral: false },
            { label: '1 not found', neutral: true },
        ]);
        const rows = element.querySelectorAll('tbody tr');
        expect(rows[0].querySelector('.not-found')).toBeNull();
        expect(text(rows[1] as HTMLElement, '.not-found')).toBe('not found');
    });

    it('uses the singular for one key and hides a zero secondary chip', () => {
        const element = render({
            mode: 'read',
            deleted_count: null,
            entries: [entry({ key: 'a', path: 'variables.a', found: true, value_preview: '1' })],
        });

        expect(text(element, '.title')).toBe('Read 1 key from profiles');
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

        expect(text(element, '.title')).toBe('Wrote 3 keys to profiles');
        expect(chips(element)).toEqual([
            { label: '1 created', neutral: false },
            { label: '2 updated', neutral: true },
        ]);
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

    it('summarises a delete with a neutral "N of M" chip and a missing-keys note', () => {
        const element = render({
            mode: 'delete',
            deleted_count: 1,
            entries: [entry({ key: 'a' }), entry({ key: 'b' }), entry({ key: 'c' })],
        });

        expect(text(element, '.title')).toBe('Removed 1 key from profiles');
        expect(chips(element)).toEqual([{ label: '1 of 3', neutral: true }]);
        expect(text(element, '.muted-note')).toBe('2 keys were not in the table');
        expect(Array.from(element.querySelectorAll('.key-chip')).map((chip) => chip.textContent)).toEqual([
            'a',
            'b',
            'c',
        ]);
        expect(element.querySelector('[class*="error"], [class*="danger"], [class*="failed"]')).toBeNull();
    });

    it('reports a delete that removed nothing without looking like an error', () => {
        const element = render({
            mode: 'delete',
            deleted_count: 0,
            entries: [entry({ key: 'a' })],
        });

        expect(text(element, '.title')).toBe('No keys removed from profiles');
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

        expect(text(element, '.title')).toBe('Removed 2 keys from profiles');
        expect(element.querySelector('.muted-note')).toBeNull();
    });

    it('starts collapsed and expands on header click', () => {
        const fixture = createFixture({ mode: 'delete', deleted_count: 1, entries: [entry({ key: 'a' })] });
        const element = fixture.nativeElement as HTMLElement;
        const header = element.querySelector<HTMLButtonElement>('.header');

        expect(element.querySelector('.content')?.classList.contains('expanded')).toBe(false);
        header?.click();
        fixture.detectChanges();
        expect(element.querySelector('.content')?.classList.contains('expanded')).toBe(true);
        expect(header?.getAttribute('aria-expanded')).toBe('true');
    });
});
