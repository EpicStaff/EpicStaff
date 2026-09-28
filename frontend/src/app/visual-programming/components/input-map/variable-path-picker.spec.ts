import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PickerItem } from './var-picker-flat.component';
import {
    buildVariablePickerItems,
    VariablePathPicker,
    VariablePathPickerRows,
    withoutUsedPaths,
} from './variable-path-picker';

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
                [attr.aria-controls]="picker.listboxIdFor($index)"
                [attr.aria-activedescendant]="picker.activeDescendantFor($index)"
                (keydown)="picker.onKeydown($index, $event)"
                (blur)="picker.onBlur($index, $event)"
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

describe('withoutUsedPaths', () => {
    const paths = (items: PickerItem[]): [string, boolean][] =>
        items.map((item) => [item.fullPath, item.disabled ?? false]);

    it('leaves out a used variable with nothing offered under it', () => {
        const used = new Set(['variables.plan', 'variables.user.id']);

        expect(paths(withoutUsedPaths(buildVariablePickerItems(STATE), used))).toEqual([
            ['variables.user', false],
            ['variables.user.tags', false],
            ['variables.user.tags[0]', false],
        ]);
    });

    it('keeps a used variable, disabled, above the variables still offered under it, at any depth', () => {
        const used = new Set(['variables.user', 'variables.user.tags']);

        expect(paths(withoutUsedPaths(buildVariablePickerItems(STATE), used))).toEqual([
            ['variables.user', true],
            ['variables.user.id', false],
            ['variables.user.tags', true],
            ['variables.user.tags[0]', false],
            ['variables.plan', false],
        ]);
    });

    it('leaves out a used object once everything under it is used as well', () => {
        const used = new Set(['variables.user', 'variables.user.id', 'variables.user.tags', 'variables.user.tags[0]']);

        expect(paths(withoutUsedPaths(buildVariablePickerItems(STATE), used))).toEqual([['variables.plan', false]]);
    });
});

describe('VariablePathPicker', () => {
    let fixture: ComponentFixture<RowsHostComponent>;
    let host: RowsHostComponent;

    const input = (row: number): HTMLInputElement => fixture.nativeElement.querySelectorAll('.row-value')[row];
    const listed = (): string[] =>
        Array.from(document.querySelectorAll<HTMLElement>('app-var-picker-flat .vpf-item'), (item) => item.title);
    const highlighted = (): string[] =>
        Array.from(document.querySelectorAll<HTMLElement>('.vpf-item--highlighted'), (item) => item.title);
    const disabled = (): string[] =>
        Array.from(document.querySelectorAll<HTMLButtonElement>('.vpf-item:disabled'), (item) => item.title);
    const press = (row: number, key: string, init: KeyboardEventInit = {}): KeyboardEvent => {
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
        input(row).dispatchEvent(event);
        fixture.detectChanges();
        return event;
    };
    const hover = (index: number): void => {
        document.querySelectorAll('.vpf-item')[index].dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
        fixture.detectChanges();
    };
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

    describe('keyboard', () => {
        let scrollIntoView: ReturnType<typeof vi.fn<Element['scrollIntoView']>>;

        beforeEach(() => {
            // jsdom does no layout, so it has no scrollIntoView.
            scrollIntoView = vi.fn<Element['scrollIntoView']>();
            Element.prototype.scrollIntoView = scrollIntoView;
        });

        afterEach(() => delete (Element.prototype as Partial<Element>).scrollIntoView);

        it('moves the highlight with the arrow keys, wrapping around, and scrolls it into view', () => {
            focus(0);
            expect(highlighted()).toEqual([]);

            const down = press(0, 'ArrowDown');
            expect(highlighted()).toEqual(['variables.user']);
            expect(down.defaultPrevented).toBe(true);
            press(0, 'ArrowDown');
            expect(highlighted()).toEqual(['variables.user.id']);
            expect(scrollIntoView).toHaveBeenLastCalledWith({ block: 'nearest' });
            expect(scrollIntoView.mock.contexts.at(-1)).toBe(document.querySelectorAll('.vpf-item')[1]);

            press(0, 'ArrowUp');
            press(0, 'ArrowUp');
            expect(highlighted()).toEqual(['variables.plan']);
            press(0, 'ArrowDown');
            expect(highlighted()).toEqual(['variables.user']);
            expect(host.picker.isOpenFor(0)).toBe(true);
        });

        it('starts from the bottom on ArrowUp, and from no highlight again once the filter changes', () => {
            focus(0);
            press(0, 'ArrowUp');
            expect(highlighted()).toEqual(['variables.plan']);

            type(0, 'variables.u');
            expect(highlighted()).toEqual([]);
        });

        it('picks the highlighted path on Enter, and leaves Enter to the host with nothing highlighted', () => {
            type(1, 'variables.us');
            expect(press(1, 'Enter').defaultPrevented).toBe(false);
            expect(host.inserted).toEqual([]);

            press(1, 'ArrowDown');
            press(1, 'ArrowDown');
            expect(press(1, 'Enter').defaultPrevented).toBe(true);

            expect(host.inserted).toEqual([[1, 'variables.user.id']]);
            expect(host.picker.isOpenFor(1)).toBe(false);
        });

        it('follows the pointer, so Enter picks the hovered row', () => {
            focus(0);
            press(0, 'ArrowDown');
            hover(4);
            expect(highlighted()).toEqual(['variables.plan']);

            press(0, 'Enter');
            expect(host.inserted).toEqual([[0, 'variables.plan']]);
        });

        it('drops the highlight when the pointer leaves the list, so Enter goes back to the host', () => {
            focus(0);
            hover(4);
            document.querySelector('.vpf-list')!.dispatchEvent(new MouseEvent('mouseleave'));
            fixture.detectChanges();

            expect(highlighted()).toEqual([]);
            expect(press(0, 'Enter').defaultPrevented).toBe(false);
            expect(host.inserted).toEqual([]);
        });

        it('picks only on a plain Enter', () => {
            focus(0);
            press(0, 'ArrowDown');

            for (const modifier of ['shiftKey', 'ctrlKey', 'altKey', 'metaKey']) {
                expect(press(0, 'Enter', { [modifier]: true }).defaultPrevented).toBe(false);
            }
            expect(host.inserted).toEqual([]);
            expect(highlighted()).toEqual(['variables.user']);
        });

        it('leaves the keys to an IME while it composes', () => {
            focus(0);
            expect(press(0, 'ArrowDown', { isComposing: true }).defaultPrevented).toBe(false);
            press(0, 'ArrowDown');
            expect(press(0, 'Enter', { isComposing: true }).defaultPrevented).toBe(false);

            expect(host.inserted).toEqual([]);
            expect(highlighted()).toEqual(['variables.user']);
        });

        it('names its list and the highlighted row to the input as a combobox, and nothing while closed', () => {
            expect(input(0).getAttribute('aria-controls')).toBeNull();
            focus(0);
            const listbox = document.querySelector('.vpf-list')!;
            expect(listbox.getAttribute('role')).toBe('listbox');
            expect(listbox.getAttribute('aria-label')).toBe('Flow variables');
            expect(input(0).getAttribute('aria-controls')).toBe(listbox.id);
            expect(input(0).getAttribute('aria-activedescendant')).toBeNull();

            press(0, 'ArrowDown');
            press(0, 'ArrowDown');
            const active = document.getElementById(input(0).getAttribute('aria-activedescendant')!);
            expect(active?.title).toBe('variables.user.id');
            expect(active?.getAttribute('aria-selected')).toBe('true');

            // Each picker has its own ids.
            focus(1);
            expect(document.querySelector('.vpf-list')!.id).not.toBe(listbox.id);
            expect(input(0).getAttribute('aria-controls')).toBeNull();
            expect(input(0).getAttribute('aria-activedescendant')).toBeNull();
        });

        it('leaves every other key to the input, and every key while closed', () => {
            focus(0);
            expect(press(0, 'a').defaultPrevented).toBe(false);

            type(0, 'user');
            expect(press(0, 'ArrowDown').defaultPrevented).toBe(false);
            expect(press(0, 'Enter').defaultPrevented).toBe(false);
        });

        it('passes a disabled row by, with the arrow keys and on hover', () => {
            host.items = withoutUsedPaths(buildVariablePickerItems(STATE), new Set(['variables.user']));
            focus(0);

            hover(0);
            expect(highlighted()).toEqual([]);
            press(0, 'ArrowDown');
            expect(highlighted()).toEqual(['variables.user.id']);
            press(0, 'ArrowUp');
            expect(highlighted()).toEqual(['variables.plan']);
        });
    });

    it('lists a used variable kept above the variables under it disabled, and never inserts it', () => {
        host.items = withoutUsedPaths(buildVariablePickerItems(STATE), new Set(['variables.user']));
        focus(0);

        expect(listed()).toEqual(buildVariablePickerItems(STATE).map((item) => item.fullPath));
        expect(disabled()).toEqual(['variables.user']);
        expect(document.querySelector('.vpf-item:disabled')!.textContent).toContain('in use');
        document.querySelector<HTMLElement>('.vpf-item:disabled')!.click();
        expect(host.inserted).toEqual([]);

        // Typed in full, it is no match to close on: the picker stays with what can be picked under it.
        type(0, 'variables.user');
        expect(host.picker.isOpenFor(0)).toBe(true);
    });

    it('has no search field of its own: the row input filters it', () => {
        focus(0);

        expect(document.querySelector('app-var-picker-flat input')).toBeNull();
        type(0, 'variables.pl');
        expect(Array.from(document.querySelectorAll<HTMLElement>('.vpf-item'), (item) => item.title)).toEqual([
            'variables.plan',
        ]);
    });

    it('closes when focus leaves the input, e.g. on Tab, but not for one of its rows or a click on a row', () => {
        focus(0);
        const row = document.querySelector<HTMLElement>('app-var-picker-flat .vpf-item')!;
        input(0).dispatchEvent(new FocusEvent('blur', { relatedTarget: row }));
        expect(host.picker.isOpenFor(0)).toBe(true);

        // A click on a row does not take focus from the input, so no blur closes the list under it.
        const rowPress = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
        document.querySelector('.vpf-item')!.dispatchEvent(rowPress);
        expect(rowPress.defaultPrevented).toBe(true);

        input(0).dispatchEvent(
            new FocusEvent('blur', { relatedTarget: fixture.nativeElement.querySelector('.outside') })
        );
        expect(host.picker.isOpenFor(0)).toBe(false);

        focus(0);
        input(0).dispatchEvent(new FocusEvent('blur'));
        expect(host.picker.isOpenFor(0)).toBe(false);
    });

    it('closes with its host', () => {
        focus(0);
        fixture.destroy();

        expect(document.querySelectorAll('app-var-picker-flat').length).toBe(0);
    });
});
