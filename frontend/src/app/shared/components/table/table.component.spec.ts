import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { AppTableComponent } from './table.component';
import { AppTableColumnDef, TableRow } from './table.model';

function renderTable(columns: AppTableColumnDef[]) {
    const fixture = TestBed.createComponent(AppTableComponent);
    fixture.componentRef.setInput('columns', columns);
    fixture.componentRef.setInput('data', [{ id: 1, name: 'a' }]);
    fixture.detectChanges();
    return { fixture, element: fixture.nativeElement as HTMLElement };
}

describe('AppTableComponent header icon', () => {
    it('renders the clickable header as a keyboard-reachable button that emits its key and anchor', () => {
        const { fixture, element } = renderTable([{ key: 'name', label: 'Name', headerIcon: 'menu' }]);
        const headerIconClick = vi.fn();
        fixture.componentInstance.headerIconClick.subscribe(headerIconClick);

        const button = element.querySelector<HTMLButtonElement>('.table-header button.col-label-group--clickable');
        expect(button?.type).toBe('button');
        button?.click();
        expect(headerIconClick).toHaveBeenCalledWith({ key: 'name', target: button });
    });

    it('sets aria-sort on the header cell only for a column that carries a sort direction', () => {
        const { element } = renderTable([
            { key: 'name', label: 'Name', headerIcon: 'arrow-up', sortDirection: 'ascending' },
            { key: 'id', label: 'Id', headerIcon: 'arrow-up-down' },
        ]);
        const cells = [...element.querySelectorAll('.table-header .table-cell')];
        expect(cells[0].getAttribute('aria-sort')).toBe('ascending');
        expect(cells[1].hasAttribute('aria-sort')).toBe(false);
    });
});

describe('AppTableComponent select all', () => {
    // Row 1 cannot be toggled but is preselected, like the current user's own membership.
    const ROWS = [
        { id: 1, name: 'locked' },
        { id: 2, name: 'b' },
        { id: 3, name: 'c' },
    ];

    function renderSelectable(initialSelectedIds: number[]) {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', [{ key: 'name', label: 'Name' }]);
        fixture.componentRef.setInput('data', ROWS);
        fixture.componentRef.setInput('selectable', true);
        fixture.componentRef.setInput('rowSelectable', (row: { id: number }) => row.id !== 1);
        fixture.componentRef.setInput('initialSelectedIds', initialSelectedIds);
        fixture.detectChanges();
        const table = fixture.componentInstance;
        const emitted: unknown[][] = [];
        table.selectionChange.subscribe((rows) => emitted.push(rows.map((row) => row['id'])));
        const selectedIds = () => table.selectedItems().map((row) => row['id']);
        return { table, emitted, selectedIds };
    }

    it('adds the selectable rows and keeps a preselected non-selectable row', () => {
        const { table, emitted, selectedIds } = renderSelectable([1]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(false);

        table.toggleAll();

        expect(selectedIds()).toEqual([1, 2, 3]);
        expect(emitted.at(-1)).toEqual([1, 2, 3]);
        expect(table.allSelected()).toBe(true);
        expect(table.indeterminate()).toBe(false);
    });

    it('removes only the selectable rows on deselect all', () => {
        const { table, emitted, selectedIds } = renderSelectable([1, 2, 3]);
        expect(table.allSelected()).toBe(true);

        table.toggleAll();

        expect(selectedIds()).toEqual([1]);
        expect(emitted.at(-1)).toEqual([1]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(false);
    });

    it('reports a partial selection of the selectable rows as indeterminate', () => {
        const { table } = renderSelectable([1, 2]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(true);

        table.toggleAll();
        expect(table.selectedItems().map((row) => row['id'])).toEqual([1, 2, 3]);
    });

    it('does nothing when no row is selectable', () => {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', [{ key: 'name', label: 'Name' }]);
        fixture.componentRef.setInput('data', ROWS);
        fixture.componentRef.setInput('selectable', true);
        fixture.componentRef.setInput('rowSelectable', () => false);
        fixture.componentRef.setInput('initialSelectedIds', [1, 2]);
        fixture.detectChanges();

        fixture.componentInstance.toggleAll();

        expect(fixture.componentInstance.selectedItems().map((row) => row['id'])).toEqual([1, 2]);
    });
});

describe('AppTableComponent rowVisible', () => {
    const ROWS = [
        { id: 1, name: 'alpha' },
        { id: 2, name: 'beta' },
        { id: 3, name: 'alpine' },
    ];
    const startsWithAl = (row: TableRow): boolean => (row['name'] as string).startsWith('al');

    function renderFiltered(initialSelectedIds: number[]) {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', [{ key: 'name', label: 'Name' }]);
        fixture.componentRef.setInput('data', ROWS);
        fixture.componentRef.setInput('selectable', true);
        fixture.componentRef.setInput('initialSelectedIds', initialSelectedIds);
        fixture.detectChanges();
        const table = fixture.componentInstance;
        const emitted: unknown[][] = [];
        table.selectionChange.subscribe((rows) => emitted.push(rows.map((row) => row['id'])));
        const setRowVisible = (predicate: ((row: TableRow) => boolean) | null): void => {
            fixture.componentRef.setInput('rowVisible', predicate);
            fixture.detectChanges();
        };
        const visibleIds = (): unknown[] => table.filteredData().map((row) => row['id']);
        const renderedRowCount = (): number =>
            (fixture.nativeElement as HTMLElement).querySelectorAll('.table-body .table-row').length;
        const selectedIds = () => table.selectedItems().map((row) => row['id']);
        return { fixture, table, emitted, setRowVisible, visibleIds, renderedRowCount, selectedIds };
    }

    it('hides rejected rows without unticking them', () => {
        const { emitted, setRowVisible, visibleIds, renderedRowCount, selectedIds } = renderFiltered([1, 2]);
        emitted.length = 0;

        setRowVisible(startsWithAl);
        expect(visibleIds()).toEqual([1, 3]);
        expect(renderedRowCount()).toBe(2);
        expect(selectedIds()).toEqual([1, 2]);
        expect(emitted).toEqual([]);

        setRowVisible(null);
        expect(visibleIds()).toEqual([1, 2, 3]);
        expect(renderedRowCount()).toBe(3);
        expect(selectedIds()).toEqual([1, 2]);
    });

    it('selects all visible rows and keeps the hidden selection', () => {
        const { table, emitted, setRowVisible, selectedIds } = renderFiltered([2]);
        setRowVisible(startsWithAl);
        expect(table.allSelected()).toBe(false);

        table.toggleAll();

        expect(selectedIds()).toEqual([1, 2, 3]);
        expect(emitted.at(-1)).toEqual([1, 2, 3]);
        expect(table.allSelected()).toBe(true);
    });

    it('deselects only the visible rows', () => {
        const { table, setRowVisible, selectedIds } = renderFiltered([1, 2, 3]);
        setRowVisible(startsWithAl);

        table.toggleAll();

        expect(selectedIds()).toEqual([2]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(false);
    });

    it('still prunes a selected row that is removed from data', () => {
        const { fixture, emitted, setRowVisible, selectedIds } = renderFiltered([1, 2]);
        setRowVisible(startsWithAl);

        fixture.componentRef.setInput('data', [ROWS[0], ROWS[2]]);
        fixture.detectChanges();

        expect(selectedIds()).toEqual([1]);
        expect(emitted.at(-1)).toEqual([1]);
    });

    it('shows the no-results state, not the empty state, when every row is hidden', () => {
        const { fixture, setRowVisible } = renderFiltered([]);

        setRowVisible(() => false);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.table-no-results')).not.toBeNull();
    });

    it('shows the empty state, not the no-results state, when data is empty', () => {
        const fixture = TestBed.createComponent(EmptyTableHostComponent);
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.table-no-results')).toBeNull();
        expect(element.querySelector('.empty-slot')?.textContent).toContain('No rows yet');
    });
});

describe('AppTableComponent customizable columns', () => {
    const LAYOUT_KEY = 'spec-table';
    const STORAGE_KEY = `app-table-layout:${LAYOUT_KEY}`;
    const COLUMNS: AppTableColumnDef[] = [
        { key: 'name', label: 'Name', width: '200px', pinned: 'start' },
        { key: 'owner', label: 'Owner', width: 'minmax(120px, 1fr)' },
        { key: 'sessions', label: 'Sessions', headerGroup: 'Retention' },
        { key: 'audit', label: 'Audit', headerGroup: 'Retention' },
        { key: 'visibility', label: 'Visibility', hiddenByDefault: true },
        { key: 'actions', label: 'Actions', width: '130px', pinned: 'end' },
    ];

    beforeEach(() => localStorage.clear());
    afterEach(() => {
        localStorage.clear();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    function render(layoutKey: string | null = LAYOUT_KEY, columns: AppTableColumnDef[] = COLUMNS) {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', columns);
        fixture.componentRef.setInput('data', [{ id: 1 }]);
        fixture.componentRef.setInput('layoutKey', layoutKey);
        fixture.detectChanges();
        const element = fixture.nativeElement as HTMLElement;
        const headerLabels = () =>
            [...element.querySelectorAll('.table-header .table-cell .col-label')].map((label) => label.textContent);
        const handle = (label: string) =>
            element.querySelector<HTMLElement>(`.resize-handle[aria-label="Resize ${label} column"]`);
        const gridTemplate = () => element.querySelector<HTMLElement>('.table-header')!.style.gridTemplateColumns;
        const pressOnHandle = (label: string, key: string) => {
            handle(label)!.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
            fixture.detectChanges();
        };
        return { fixture, element, headerLabels, handle, gridTemplate, pressOnHandle };
    }

    function storedLayout(): unknown {
        return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
    }

    it('renders a table without a layoutKey as before: every column, no handles, no layout stored', () => {
        const plainColumns: AppTableColumnDef[] = [
            { key: 'name', label: 'Name', width: '200px' },
            { key: 'owner', label: 'Owner' },
            { key: 'extra', label: 'Extra', hiddenByDefault: true },
        ];
        const { element, headerLabels, gridTemplate } = render(null, plainColumns);

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Extra']);
        expect(gridTemplate()).toBe('200px 1fr 1fr');
        expect(element.querySelector('.resize-handle')).toBeNull();
        expect(element.querySelector('.table-wrapper--customizable, .pinned-start, .pinned-end')).toBeNull();
        expect(localStorage.length).toBe(0);
    });

    it('hides a hiddenByDefault column and offers no resize handle on pinned columns', () => {
        const { headerLabels, handle, element } = render();

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Sessions', 'Audit', 'Actions']);
        expect(handle('Owner')).not.toBeNull();
        expect(handle('Name')).toBeNull();
        expect(handle('Actions')).toBeNull();
        expect(element.querySelector('.table-header-group')?.textContent?.trim()).toBe('Retention');
    });

    it('shows exactly the chosen columns, keeps pinned ones and stores the choice', () => {
        const { fixture, headerLabels, element } = render();

        fixture.componentInstance.setVisibleColumns(['owner', 'visibility', 'unknown']);
        fixture.detectChanges();

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Visibility', 'Actions']);
        expect(element.querySelector('.table-header-group')).toBeNull();
        expect(storedLayout()).toEqual({
            visibility: { owner: true, sessions: false, audit: false, visibility: true },
            widths: {},
        });
    });

    it('restores stored visibility and widths, ignoring unknown columns and invalid entries', () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({
                visibility: { owner: false, gone: true, audit: 'no' },
                widths: { sessions: 150, owner: -5, audit: 'wide' },
            })
        );

        const { headerLabels, gridTemplate } = render();

        expect(headerLabels()).toEqual(['Name', 'Sessions', 'Audit', 'Actions']);
        expect(gridTemplate()).toBe('200px 150px 1fr 130px');
    });

    it.each([
        ['broken JSON', '{not json'],
        ['an array', '[1, 2]'],
        ['null', 'null'],
        ['records of the wrong type', '{"visibility": [true], "widths": "wide"}'],
    ])('falls back to the default columns when storage holds %s', (_case, raw) => {
        localStorage.setItem(STORAGE_KEY, raw);

        const { headerLabels } = render();

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Sessions', 'Audit', 'Actions']);
    });

    it('still works for the session when storage throws', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('storage disabled');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('storage disabled');
        });
        const { fixture, headerLabels } = render();
        expect(headerLabels()).toEqual(['Name', 'Owner', 'Sessions', 'Audit', 'Actions']);

        fixture.componentInstance.setVisibleColumns(['owner']);
        fixture.detectChanges();

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Actions']);
    });

    it('resizes a column from the keyboard, never below 80px, and stores the width', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ visibility: {}, widths: { owner: 100 } }));
        const { handle, gridTemplate, pressOnHandle } = render();

        pressOnHandle('Owner', 'ArrowLeft');
        expect(handle('Owner')!.getAttribute('aria-valuenow')).toBe('84');

        pressOnHandle('Owner', 'ArrowLeft');
        pressOnHandle('Owner', 'ArrowLeft');
        expect(handle('Owner')!.getAttribute('aria-valuenow')).toBe('80');
        expect(gridTemplate()).toBe('200px 80px 1fr 1fr 130px');

        pressOnHandle('Owner', 'ArrowRight');
        expect(handle('Owner')!.getAttribute('aria-valuenow')).toBe('96');
        expect(storedLayout()).toEqual({ visibility: {}, widths: { owner: 96 } });
    });

    it('raises a stored width below the minimum to 80px and resizes on from there', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ visibility: {}, widths: { owner: 20 } }));

        const { handle, gridTemplate, pressOnHandle } = render();
        expect(gridTemplate()).toBe('200px 80px 1fr 1fr 130px');
        expect(handle('Owner')!.getAttribute('aria-valuenow')).toBe('80');

        pressOnHandle('Owner', 'ArrowRight');
        expect(handle('Owner')!.getAttribute('aria-valuenow')).toBe('96');
    });

    it('reports the rendered width and fixes every resizable column in px on the first resize', () => {
        const observers: ResizeObserverStub[] = [];
        class ResizeObserverStub {
            readonly observed: Element[] = [];
            constructor(readonly callback: (entries: Partial<ResizeObserverEntry>[]) => void) {
                observers.push(this);
            }
            observe(target: Element): void {
                this.observed.push(target);
            }
            disconnect(): void {}
        }
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        const { fixture, handle, gridTemplate, pressOnHandle } = render();
        const observer = observers.at(-1)!;
        const renderedWidths = [300, 150, 151];
        observer.callback(
            observer.observed.map((target, index) => ({
                target,
                borderBoxSize: [{ inlineSize: renderedWidths[index], blockSize: 36 }],
            }))
        );
        fixture.detectChanges();
        expect(handle('Sessions')!.getAttribute('aria-valuenow')).toBe('150');
        expect(handle('Sessions')!.getAttribute('aria-valuetext')).toBe('150 pixels');
        expect(gridTemplate()).toBe('200px minmax(120px, 1fr) 1fr 1fr 130px');

        pressOnHandle('Sessions', 'ArrowRight');

        expect(gridTemplate()).toBe('200px 300px 166px 151px 130px');
        expect(storedLayout()).toEqual({ visibility: {}, widths: { owner: 300, sessions: 166, audit: 151 } });
    });

    it('places the header group, the pinned columns and their offsets around the checkbox column', () => {
        const { fixture, element } = render();
        fixture.componentRef.setInput('selectable', true);
        fixture.componentInstance.setVisibleColumns(['sessions', 'audit']);
        fixture.detectChanges();

        const headerCell = (selector: string) => element.querySelector<HTMLElement>(`.table-header ${selector}`)!;
        // Lines: checkbox 1, Name 2, Sessions 3, Audit 4.
        expect(headerCell('.table-header-group').style.gridArea).toBe('1 / 3 / auto / span 2');
        expect(headerCell('.table-cell.pinned-start:not(.checkbox)').style.left).toBe('calc(2rem)');
        expect(headerCell('.table-cell.pinned-end').style.right).toBe('0px');
    });
});

@Component({
    imports: [AppTableComponent],
    template: `
        <app-table
            [columns]="columns"
            [data]="[]"
            [rowVisible]="hideEveryRow"
        >
            <div
                tableEmpty
                class="empty-slot"
            >
                No rows yet
            </div>
        </app-table>
    `,
})
class EmptyTableHostComponent {
    readonly columns: AppTableColumnDef[] = [{ key: 'name', label: 'Name' }];
    readonly hideEveryRow = (): boolean => false;
}
