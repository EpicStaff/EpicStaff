import { Dialog } from '@angular/cdk/dialog';
import { DOWN_ARROW, ENTER, ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService } from '@shared/components';

import { KeyValueTable } from '../../models/key-value-table.model';
import { KeyValueTableListComponent } from './key-value-table-list.component';

const TABLE: KeyValueTable = {
    id: 1,
    name: 'profiles',
    description: '',
    entry_count: 3,
    created_at: '2026-09-24T00:00:00Z',
    updated_at: '2026-09-24T00:00:00Z',
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    last_edited_by: { id: 2, display_name: 'Olena Petrenko', avatar_url: null },
    last_edited_at: '2026-09-25T00:00:00Z',
};

interface RenderedList {
    fixture: ComponentFixture<KeyValueTableListComponent>;
    element: HTMLElement;
    overlay: HTMLElement;
    trigger: HTMLButtonElement;
}

function renderList(canRename: boolean, canDelete: boolean): RenderedList {
    const fixture = TestBed.createComponent(KeyValueTableListComponent);
    fixture.componentRef.setInput('tables', [TABLE]);
    fixture.componentRef.setInput('canRename', canRename);
    fixture.componentRef.setInput('canDelete', canDelete);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    return {
        fixture,
        element,
        overlay: TestBed.inject(OverlayContainer).getContainerElement(),
        trigger: element.querySelector<HTMLButtonElement>('[aria-label="More actions for profiles"]')!,
    };
}

function openMenu({ fixture, trigger }: RenderedList): void {
    trigger.click();
    fixture.detectChanges();
}

function menuItems(overlay: HTMLElement): HTMLButtonElement[] {
    return [...overlay.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
}

function menuItemLabels(overlay: HTMLElement): (string | undefined)[] {
    return menuItems(overlay).map((item) => item.textContent?.trim());
}

function menuItem(overlay: HTMLElement, label: string): HTMLButtonElement {
    return menuItems(overlay).find((item) => item.textContent?.trim() === label)!;
}

/** CDK menus read the legacy `keyCode`, which a synthetic `KeyboardEvent` cannot be constructed with. */
function pressKey(target: HTMLElement, key: string, keyCode: number): void {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    Object.defineProperty(event, 'keyCode', { get: () => keyCode });
    target.dispatchEvent(event);
}

describe('KeyValueTableListComponent row menu', () => {
    it.each([
        { canRename: true, canDelete: true, labels: ['Rename', 'View Details', 'Delete'] },
        { canRename: true, canDelete: false, labels: ['Rename', 'View Details'] },
        { canRename: false, canDelete: true, labels: ['View Details', 'Delete'] },
        { canRename: false, canDelete: false, labels: ['View Details'] },
    ])('lists $labels with rename $canRename and delete $canDelete', ({ canRename, canDelete, labels }) => {
        const list = renderList(canRename, canDelete);
        expect(list.trigger).not.toBeNull();

        openMenu(list);

        expect(list.overlay.querySelector('[role="menu"]')).not.toBeNull();
        expect(menuItemLabels(list.overlay)).toEqual(labels);
    });

    it('opens the menu without selecting the row', () => {
        const list = renderList(true, true);
        const selected = vi.fn();
        list.fixture.componentInstance.selected.subscribe(selected);

        openMenu(list);

        expect(menuItems(list.overlay)).toHaveLength(3);
        expect(selected).not.toHaveBeenCalled();
    });

    it.each([
        { label: 'Rename', output: 'renameRequested' as const },
        { label: 'Delete', output: 'deleteRequested' as const },
    ])('emits $output with the table, closes the menu and focuses the ⋮ on "$label"', ({ label, output }) => {
        const list = renderList(true, true);
        const emitted = vi.fn();
        list.fixture.componentInstance[output].subscribe(emitted);
        const selected = vi.fn();
        list.fixture.componentInstance.selected.subscribe(selected);

        openMenu(list);
        menuItem(list.overlay, label).click();
        list.fixture.detectChanges();

        expect(emitted).toHaveBeenCalledExactlyOnceWith(TABLE);
        expect(selected).not.toHaveBeenCalled();
        expect(menuItems(list.overlay)).toHaveLength(0);
        expect(document.activeElement).toBe(list.trigger);
    });

    it('opens the table details dialog with the table and the ⋮ to return focus to on "View Details"', () => {
        const list = renderList(false, false);
        const open = vi.spyOn(TestBed.inject(AuthorshipDetailsDialogService), 'open');

        openMenu(list);
        menuItem(list.overlay, 'View Details').click();
        list.fixture.detectChanges();

        expect(open).toHaveBeenCalledExactlyOnceWith('Table Details', TABLE, list.trigger);
        expect(list.overlay.querySelector('[role="menu"]')).toBeNull();
    });

    it('can be opened and an item chosen with the keyboard alone', () => {
        const list = renderList(true, true);
        const renameRequested = vi.fn();
        list.fixture.componentInstance.renameRequested.subscribe(renameRequested);
        list.trigger.focus();

        pressKey(list.trigger, 'ArrowDown', DOWN_ARROW);
        list.fixture.detectChanges();

        const rename = menuItem(list.overlay, 'Rename');
        expect(document.activeElement).toBe(rename);

        pressKey(rename, 'Enter', ENTER);
        list.fixture.detectChanges();

        expect(renameRequested).toHaveBeenCalledExactlyOnceWith(TABLE);
        expect(menuItems(list.overlay)).toHaveLength(0);
        expect(document.activeElement).toBe(list.trigger);
    });

    it('closes only the menu on Escape and returns focus to the ⋮', () => {
        const list = renderList(true, true);
        const emitted = vi.fn();
        list.fixture.componentInstance.renameRequested.subscribe(emitted);
        list.fixture.componentInstance.deleteRequested.subscribe(emitted);
        list.fixture.componentInstance.selected.subscribe(emitted);

        openMenu(list);
        pressKey(menuItem(list.overlay, 'Rename'), 'Escape', ESCAPE);
        list.fixture.detectChanges();

        expect(menuItems(list.overlay)).toHaveLength(0);
        expect(document.activeElement).toBe(list.trigger);
        expect(emitted).not.toHaveBeenCalled();
    });

    it('keeps the row marked while its menu is open', () => {
        const list = renderList(true, true);
        const row = list.element.querySelector('.table-list__row')!;

        openMenu(list);
        expect(row.classList).toContain('table-list__row--menu-open');

        list.trigger.click();
        list.fixture.detectChanges();
        expect(row.classList).not.toContain('table-list__row--menu-open');
    });

    it('returns focus to the ⋮ once the details dialog closes', () => {
        const list = renderList(false, false);
        const dialog = TestBed.inject(Dialog);

        openMenu(list);
        menuItem(list.overlay, 'View Details').click();
        list.fixture.detectChanges();
        expect(dialog.openDialogs).toHaveLength(1);
        expect(list.overlay.textContent).toContain('Table Details');

        dialog.openDialogs[0].close();
        list.fixture.detectChanges();

        expect(dialog.openDialogs).toHaveLength(0);
        expect(document.activeElement).toBe(list.trigger);
    });
});

function renderTables(count: number) {
    const fixture = TestBed.createComponent(KeyValueTableListComponent);
    const tables = Array.from({ length: count }, (_, index) => ({
        ...TABLE,
        id: index + 1,
        name: `table_${index + 1}`,
    }));
    fixture.componentRef.setInput('tables', tables);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const names = () => [...element.querySelectorAll('.table-list__name')].map((name) => name.textContent?.trim());
    return { fixture, element, names };
}

describe('KeyValueTableListComponent name filter', () => {
    it('hides the filter for 8 tables or fewer', () => {
        const { element, names } = renderTables(8);
        expect(element.querySelector('app-search')).toBeNull();
        expect(names()).toHaveLength(8);
    });

    it('shows "Filter tables..." past 8 tables and filters names client-side', () => {
        const { fixture, element, names } = renderTables(9);
        const input = element.querySelector<HTMLInputElement>('app-search input');
        expect(input?.placeholder).toBe('Filter tables...');

        fixture.componentInstance.filterText.set('TABLE_9');
        fixture.detectChanges();
        expect(names()).toEqual(['table_9']);

        fixture.componentInstance.filterText.set('nothing');
        fixture.detectChanges();
        expect(element.querySelector('.table-list__empty')?.textContent?.trim()).toBe('No tables match your filter');
    });

    it('ignores a leftover filter once the list drops back to 8 tables', () => {
        const { fixture, names } = renderTables(9);
        fixture.componentInstance.filterText.set('table_9');
        fixture.componentRef.setInput(
            'tables',
            Array.from({ length: 8 }, (_, index) => ({ ...TABLE, id: index + 1, name: `table_${index + 1}` }))
        );
        fixture.detectChanges();
        expect(names()).toHaveLength(8);
    });
});

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('KeyValueTableListComponent header', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function renderHeader(canCreate: boolean) {
        const fixture = TestBed.createComponent(KeyValueTableListComponent);
        fixture.componentRef.setInput('tables', [TABLE, { ...TABLE, id: 2, name: 'orders' }]);
        fixture.componentRef.setInput('canCreate', canCreate);
        fixture.detectChanges();
        const element = fixture.nativeElement as HTMLElement;
        const addButton = element.querySelector<HTMLElement>('.table-list__header app-button');
        return { fixture, element, addButton };
    }

    it('reads "Tables" with the table count', () => {
        const { element } = renderHeader(false);
        expect(element.querySelector('.table-list__header-label')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
            'Tables 2'
        );
    });

    it('offers Add only with create permission and emits createRequested on click', () => {
        expect(renderHeader(false).addButton).toBeNull();

        const { fixture, addButton } = renderHeader(true);
        const createRequested = vi.fn();
        fixture.componentInstance.createRequested.subscribe(createRequested);
        expect(addButton?.textContent?.trim()).toBe('Add');
        addButton?.click();
        expect(createRequested).toHaveBeenCalledOnce();
    });
});
