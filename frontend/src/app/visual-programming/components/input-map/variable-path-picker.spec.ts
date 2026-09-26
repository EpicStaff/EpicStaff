import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PickerItem } from './var-picker-flat.component';
import { buildVariablePickerItems, VariablePathPicker, VariablePathPickerRows } from './variable-path-picker';

const STATE = { variables: { user: { id: 1, tags: ['a'] }, plan: 'free' } };

// Stands in for the Input List: rows whose value inputs call the picker the way input-map's template does.
@Component({
    template: `
        @for (value of values(); track $index) {
            <input
                class="row-value"
                [value]="value"
                (focus)="picker.onFocus($index, $event)"
                (input)="picker.onInput($index, $event)"
            />
        }
        <button
            type="button"
            class="outside"
        >
            Outside
        </button>
    `,
})
class RowsHostComponent {
    readonly values = signal(['variables.', 'variables.']);
    items: PickerItem[] = buildVariablePickerItems(STATE);
    readonly inserted: [number, string][] = [];
    readonly rows: VariablePathPickerRows = {
        itemsFor: () => this.items,
        insert: (rowIndex, path) => this.inserted.push([rowIndex, path]),
    };
    readonly picker = new VariablePathPicker(this.rows);
}

describe('buildVariablePickerItems', () => {
    it('lists every variable path, each parent first, tagged and indented by depth', () => {
        expect(buildVariablePickerItems(STATE)).toEqual([
            { tag: 'obj', label: 'user', displayLabel: 'user', depth: 0, fullPath: 'variables.user' },
            { tag: 'var', label: 'user.id', displayLabel: 'id', depth: 1, fullPath: 'variables.user.id' },
            { tag: 'obj', label: 'user.tags', displayLabel: 'tags', depth: 1, fullPath: 'variables.user.tags' },
            { tag: 'var', label: 'user.tags[0]', displayLabel: '0', depth: 2, fullPath: 'variables.user.tags[0]' },
            { tag: 'var', label: 'plan', displayLabel: 'plan', depth: 0, fullPath: 'variables.plan' },
        ]);
    });

    it('has nothing to list without variables', () => {
        expect(buildVariablePickerItems({})).toEqual([]);
        expect(buildVariablePickerItems({ variables: 'text' })).toEqual([]);
    });
});

describe('VariablePathPicker', () => {
    let fixture: ComponentFixture<RowsHostComponent>;
    let host: RowsHostComponent;

    const input = (row: number): HTMLInputElement => fixture.nativeElement.querySelectorAll('.row-value')[row];
    const listed = (): string[] =>
        Array.from(document.querySelectorAll<HTMLElement>('app-var-picker-flat .vpf-item'), (item) => item.title);
    const focus = (row: number): void => {
        input(row).dispatchEvent(new FocusEvent('focus'));
        fixture.detectChanges();
    };
    const type = (row: number, text: string): void => {
        input(row).value = text;
        input(row).dispatchEvent(new Event('input'));
        fixture.detectChanges();
    };

    beforeEach(() => {
        fixture = TestBed.createComponent(RowsHostComponent);
        host = fixture.componentInstance;
        fixture.detectChanges();
    });

    afterEach(() => fixture.destroy());

    it('opens on focus once the value starts with variables., listing what the row is offered', () => {
        focus(0);
        expect(host.picker.isOpenFor(0)).toBe(true);
        expect(listed()).toEqual(buildVariablePickerItems(STATE).map((item) => item.fullPath));

        host.picker.close();
        type(1, 'plan');
        focus(1);
        expect(listed()).toEqual([]);
    });

    it('does not open on focus for a value that already names a variable', () => {
        input(0).value = 'variables.plan';
        focus(0);

        expect(host.picker.isOpenFor(0)).toBe(false);
    });

    it('filters by what follows the prefix while typing, and closes on an exact match or without the prefix', () => {
        type(0, 'variables.US');
        expect(host.picker.isOpenFor(0)).toBe(true);
        expect(listed()).toEqual([
            'variables.user',
            'variables.user.id',
            'variables.user.tags',
            'variables.user.tags[0]',
        ]);

        type(0, 'variables.user.id');
        expect(host.picker.isOpenFor(0)).toBe(false);

        type(0, 'variables.us');
        type(0, 'user');
        expect(host.picker.isOpenFor(0)).toBe(false);
    });

    it('keeps each match under the parents the row is offered, never under a sibling', () => {
        type(0, 'variables.tags[');
        expect(listed()).toEqual(['variables.user', 'variables.user.tags', 'variables.user.tags[0]']);
        host.picker.close();

        // As when another row uses `variables.user.tags`.
        host.items = buildVariablePickerItems(STATE).filter((item) => item.fullPath !== 'variables.user.tags');
        type(0, 'variables.[0]');
        expect(listed()).toEqual(['variables.user', 'variables.user.tags[0]']);
    });

    it('puts the clicked path into the row it is open for, then closes', () => {
        type(1, 'variables.pl');
        document.querySelector<HTMLElement>('.vpf-item')!.click();
        fixture.detectChanges();

        expect(host.inserted).toEqual([[1, 'variables.plan']]);
        expect(listed()).toEqual([]);
    });

    it('covers one row at a time', () => {
        focus(0);
        focus(1);

        expect(host.picker.isOpenFor(0)).toBe(false);
        expect(host.picker.isOpenFor(1)).toBe(true);
        expect(document.querySelectorAll('app-var-picker-flat').length).toBe(1);
    });

    it('closes on Escape and on a click outside, but not on a click in its own input', () => {
        focus(0);
        input(0).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        expect(host.picker.isOpenFor(0)).toBe(false);

        focus(0);
        input(0).dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
        input(0).dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(host.picker.isOpenFor(0)).toBe(true);

        const outside: HTMLElement = fixture.nativeElement.querySelector('.outside');
        outside.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
        outside.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        expect(host.picker.isOpenFor(0)).toBe(false);
    });

    it('keeps the Escape that closes it from reaching the window, and lets the next one through', () => {
        const windowKeydown = vi.fn();
        window.addEventListener('keydown', windowKeydown);
        try {
            focus(0);
            input(0).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            expect(host.picker.isOpenFor(0)).toBe(false);
            expect(windowKeydown).not.toHaveBeenCalled();

            input(0).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            expect(windowKeydown).toHaveBeenCalledTimes(1);
        } finally {
            window.removeEventListener('keydown', windowKeydown);
        }
    });

    it('matches and filters on the whole value, or on the path pathOf finds in it', () => {
        // The Input List gives no pathOf: `|0` is just more text to filter by.
        type(0, 'variables.plan|0');
        expect(host.picker.isOpenFor(0)).toBe(true);
        expect(listed()).toEqual([]);
        host.picker.close();

        host.rows.pathOf = (value) => value.split('|')[0];
        type(0, 'variables.plan|0');
        expect(host.picker.isOpenFor(0)).toBe(false);
        focus(0);
        expect(host.picker.isOpenFor(0)).toBe(false);

        type(0, 'variables.pl|0');
        expect(listed()).toEqual(['variables.plan']);
    });

    it('closes with its host', () => {
        focus(0);
        fixture.destroy();

        expect(document.querySelectorAll('app-var-picker-flat').length).toBe(0);
    });
});
