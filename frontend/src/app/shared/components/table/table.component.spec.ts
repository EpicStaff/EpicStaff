import { ApplicationRef, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { AppTableComponent } from './table.component';
import { AppTableColumnDef, TableRow } from './table.model';
import { AppTableCellDirective } from './table-cell.directive';

/**
 * jsdom has no ResizeObserver: a stub one lets a spec report the rendered width of each observed header cell, by
 * its label.
 */
function stubResizeObserver(): (widthsByLabel: Record<string, number>) => void {
    const observers: { observed: Element[]; callback: (entries: Partial<ResizeObserverEntry>[]) => void }[] = [];
    vi.stubGlobal(
        'ResizeObserver',
        class {
            readonly observed: Element[] = [];
            constructor(readonly callback: (entries: Partial<ResizeObserverEntry>[]) => void) {
                observers.push(this);
            }
            observe(target: Element): void {
                this.observed.push(target);
            }
            disconnect(): void {}
        }
    );
    return (widthsByLabel) => {
        const observer = observers
            .filter((candidate) => candidate.observed.some((target) => target.classList.contains('table-cell')))
            .at(-1)!;
        observer.callback(
            observer.observed
                .filter((target) => widthsByLabel[target.textContent?.trim() ?? ''] !== undefined)
                .map((target) => ({
                    target,
                    borderBoxSize: [{ inlineSize: widthsByLabel[target.textContent!.trim()], blockSize: 36 }],
                }))
        );
    };
}

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

    it('hides a hiddenByDefault column and offers a resize handle on every column but the end-pinned one', () => {
        const { headerLabels, handle, element } = render();

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Sessions', 'Audit', 'Actions']);
        expect(handle('Owner')).not.toBeNull();
        expect(handle('Name')).not.toBeNull();
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

    it.each([
        [
            'the last start-pinned one, once every other column has a px width',
            COLUMNS,
            { owner: 100, sessions: 100, audit: 100, actions: 300 },
            'minmax(200px, 1fr) 100px 100px 100px 130px',
        ],
        [
            'the last start-pinned one, from its stored width',
            COLUMNS,
            { name: 260, owner: 100, sessions: 100, audit: 100 },
            'minmax(260px, 1fr) 100px 100px 100px 130px',
        ],
        [
            'none while another column still flexes',
            COLUMNS,
            { owner: 100, sessions: 100 },
            '200px 100px 100px 1fr 130px',
        ],
        [
            'the first scrolling one when no column is start-pinned',
            [
                { key: 'owner', label: 'Owner', width: '150px' },
                { key: 'sessions', label: 'Sessions' },
                { key: 'actions', label: 'Actions', width: '130px', pinned: 'end' as const },
            ],
            { sessions: 100 },
            'minmax(150px, 1fr) 100px 130px',
        ],
    ])(
        'lets one column fill the leftover space so Actions stays at the end: %s',
        (_case, columns, widths, expected) => {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({ visibility: {}, widths }));

            const { gridTemplate } = render(LAYOUT_KEY, columns);

            expect(gridTemplate()).toBe(expected);
        }
    );

    it('raises a stored width below the minimum to 80px and resizes on from there', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ visibility: {}, widths: { owner: 20 } }));

        const { handle, gridTemplate, pressOnHandle } = render();
        expect(gridTemplate()).toBe('200px 80px 1fr 1fr 130px');
        expect(handle('Owner')!.getAttribute('aria-valuenow')).toBe('80');

        pressOnHandle('Owner', 'ArrowRight');
        expect(handle('Owner')!.getAttribute('aria-valuenow')).toBe('96');
    });

    it('reports the rendered width and fixes every resizable column in px on the first resize', () => {
        const reportWidths = stubResizeObserver();
        const { fixture, handle, gridTemplate, pressOnHandle } = render();
        reportWidths({ Name: 200, Owner: 300, Sessions: 150, Audit: 151 });
        fixture.detectChanges();
        expect(handle('Sessions')!.getAttribute('aria-valuenow')).toBe('150');
        expect(handle('Sessions')!.getAttribute('aria-valuetext')).toBe('150 pixels');
        expect(gridTemplate()).toBe('200px minmax(120px, 1fr) 1fr 1fr 130px');

        pressOnHandle('Sessions', 'ArrowRight');

        expect(gridTemplate()).toBe('minmax(200px, 1fr) 300px 166px 151px 130px');
        expect(storedLayout()).toEqual({
            visibility: {},
            widths: { name: 200, owner: 300, sessions: 166, audit: 151 },
        });
    });

    it('keeps the shown columns at their width when one is hidden, and stretches the first column instead', () => {
        const reportWidths = stubResizeObserver();
        const { fixture, gridTemplate } = render();
        reportWidths({ Name: 200, Owner: 300, Sessions: 150, Audit: 151 });

        fixture.componentInstance.setVisibleColumns(['owner', 'audit']);
        fixture.detectChanges();

        expect(gridTemplate()).toBe('minmax(200px, 1fr) 300px 151px 130px');
        expect(storedLayout()).toEqual({
            visibility: { owner: true, sessions: false, audit: true, visibility: false },
            widths: { owner: 300, sessions: 150, audit: 151 },
        });
    });

    it('keeps the shown columns at their width when one is added, and shrinks the stretched first column back', () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ visibility: {}, widths: { owner: 300, sessions: 150, audit: 151 } })
        );
        const reportWidths = stubResizeObserver();
        const { fixture, gridTemplate } = render();
        expect(gridTemplate()).toBe('minmax(200px, 1fr) 300px 150px 151px 130px');
        reportWidths({ Name: 420, Owner: 300, Sessions: 150, Audit: 151 });

        fixture.componentInstance.setVisibleColumns(['owner', 'sessions', 'audit', 'visibility']);
        fixture.detectChanges();

        // Visibility has no width yet, so it takes the leftover space Name gives back.
        expect(gridTemplate()).toBe('200px 300px 150px 151px 1fr 130px');
        expect(storedLayout()).toEqual({
            visibility: { owner: true, sessions: true, audit: true, visibility: true },
            widths: { owner: 300, sessions: 150, audit: 151 },
        });
    });

    it('drags the stretched first column from its rendered width, so its edge does not jump', () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ visibility: {}, widths: { owner: 300, sessions: 150, audit: 151 } })
        );
        const reportWidths = stubResizeObserver();
        const { fixture, handle, gridTemplate } = render();
        reportWidths({ Name: 420, Owner: 300, Sessions: 150, Audit: 151 });
        fixture.detectChanges();
        const nameHandle = handle('Name')!;
        expect(nameHandle.getAttribute('aria-valuenow')).toBe('420');
        nameHandle.setPointerCapture = () => undefined;

        nameHandle.dispatchEvent(new PointerEvent('pointerdown', { clientX: 500, button: 0 }));
        nameHandle.dispatchEvent(new PointerEvent('pointermove', { clientX: 510 }));
        fixture.detectChanges();

        expect(gridTemplate()).toBe('minmax(430px, 1fr) 300px 150px 151px 130px');
    });

    it('always shows a column that is not hideable, leaves it out of the picker list and keeps it resizable', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ visibility: { owner: false }, widths: {} }));
        const columns = COLUMNS.map((col) => (col.key === 'owner' ? { ...col, hideable: false as const } : col));
        const { fixture, headerLabels, handle } = render(LAYOUT_KEY, columns);
        const table = fixture.componentInstance;

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Sessions', 'Audit', 'Actions']);
        expect(table.hideableColumns().map((col) => col.key)).toEqual(['sessions', 'audit', 'visibility']);
        expect(handle('Owner')).not.toBeNull();

        table.setVisibleColumns(['visibility']);
        fixture.detectChanges();

        expect(headerLabels()).toEqual(['Name', 'Owner', 'Visibility', 'Actions']);
        expect(storedLayout()).toEqual({
            visibility: { sessions: false, audit: false, visibility: true },
            widths: {},
        });
    });

    it('draws the resize line down the column while its handle is hovered, focused or dragged', () => {
        const { fixture, element, handle } = render();
        const lineColumns = () => {
            fixture.detectChanges();
            const cells = [...element.querySelectorAll('.table-body .table-row:first-child > .table-cell')];
            return cells.flatMap((cell, index) => (cell.classList.contains('resize-line') ? [index] : []));
        };
        const ownerHandle = handle('Owner')!;
        ownerHandle.setPointerCapture = () => undefined;

        ownerHandle.dispatchEvent(new PointerEvent('pointerenter'));
        expect(lineColumns()).toEqual([1]);
        ownerHandle.dispatchEvent(new PointerEvent('pointerleave'));
        expect(lineColumns()).toEqual([]);

        ownerHandle.dispatchEvent(new FocusEvent('focus'));
        expect(lineColumns()).toEqual([1]);
        ownerHandle.dispatchEvent(new FocusEvent('blur'));
        expect(lineColumns()).toEqual([]);

        ownerHandle.dispatchEvent(new PointerEvent('pointerdown', { clientX: 0, button: 0 }));
        ownerHandle.dispatchEvent(new PointerEvent('pointerleave'));
        expect(lineColumns()).toEqual([1]);
        ownerHandle.dispatchEvent(new PointerEvent('pointerup'));
        expect(lineColumns()).toEqual([]);
    });

    it('explains the double-click on the resize handle in a tooltip, hidden while dragging', () => {
        const { fixture, handle } = render();
        const tooltip = fixture.debugElement
            .query(By.css('.resize-handle[aria-label="Resize Owner column"]'))
            .injector.get(MatTooltip);
        expect(tooltip.message).toBe('Drag to resize. Double-click to fit all columns to the screen.');
        expect(tooltip.disabled).toBe(false);
        const ownerHandle = handle('Owner')!;
        ownerHandle.setPointerCapture = () => undefined;

        ownerHandle.dispatchEvent(new PointerEvent('pointerdown', { clientX: 0, button: 0 }));
        fixture.detectChanges();
        expect(tooltip.disabled).toBe(true);

        ownerHandle.dispatchEvent(new PointerEvent('pointerup'));
        fixture.detectChanges();
        expect(tooltip.disabled).toBe(false);
    });

    it('resizes a start-pinned column, which stays sticky and pushes the offset of the next pinned column', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ visibility: {}, widths: { name: 260, actions: 300 } }));
        const columns: AppTableColumnDef[] = [
            { key: 'name', label: 'Name', width: '200px', pinned: 'start' },
            { key: 'email', label: 'Email', width: '120px', pinned: 'start' },
            { key: 'owner', label: 'Owner' },
            { key: 'actions', label: 'Actions', width: '130px', pinned: 'end' },
        ];
        const { fixture, element, gridTemplate, pressOnHandle } = render(LAYOUT_KEY, columns);
        fixture.componentRef.setInput('selectable', true);
        fixture.detectChanges();
        const headerCell = (label: string) =>
            [...element.querySelectorAll<HTMLElement>('.table-header .table-cell')].find(
                (cell) => cell.textContent?.trim() === label
            )!;

        // A stored width of the end-pinned column is ignored. The DOM serializes calc() terms px first.
        expect(gridTemplate()).toBe('2rem 260px 120px 1fr 130px');
        expect(headerCell('Email').style.left).toBe('calc(260px + 2rem)');

        pressOnHandle('Name', 'ArrowRight');

        expect(headerCell('Name').classList).toContain('pinned-start');
        expect(gridTemplate()).toBe('2rem 276px 120px 1fr 130px');
        expect(headerCell('Email').style.left).toBe('calc(276px + 2rem)');
        expect(storedLayout()).toEqual({ visibility: {}, widths: { name: 276, actions: 300 } });
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

describe('AppTableComponent horizontal scroll with pinned columns', () => {
    const COLUMNS: AppTableColumnDef[] = [
        { key: 'name', label: 'Name', width: '200px', pinned: 'start' },
        { key: 'owner', label: 'Owner', width: '600px' },
        { key: 'actions', label: 'Actions', width: '130px', pinned: 'end' },
    ];

    afterEach(() => vi.restoreAllMocks());

    /** jsdom does no layout: the wrapper's geometry is set by hand, and its scrollLeft made writable. */
    function render(columns: AppTableColumnDef[] = COLUMNS) {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', columns);
        fixture.componentRef.setInput('data', [{ id: 1 }]);
        fixture.componentRef.setInput('selectable', true);
        fixture.detectChanges();
        const element = fixture.nativeElement as HTMLElement;
        const wrapper = element.querySelector<HTMLElement>('.table-wrapper')!;
        const geometry = { scrollLeft: 0, scrollWidth: 1000, clientWidth: 600, offsetWidth: 608, clientLeft: 1 };
        for (const [property, value] of Object.entries(geometry)) {
            Object.defineProperty(wrapper, property, { value, writable: true, configurable: true });
        }
        const scrollWrapperTo = (scrollLeft: number) => {
            wrapper.scrollLeft = scrollLeft;
            wrapper.dispatchEvent(new Event('scroll'));
            fixture.detectChanges();
        };
        const scrollbar = () => element.querySelector<HTMLElement>('.table-scrollbar');
        const shadows = () => ({
            start: wrapper.classList.contains('table-wrapper--shadow-start'),
            end: wrapper.classList.contains('table-wrapper--shadow-end'),
        });
        return { fixture, element, wrapper, scrollWrapperTo, scrollbar, shadows };
    }

    it.each([
        ['at the start', 0, { start: false, end: true }],
        ['in the middle', 200, { start: true, end: true }],
        ['at the end', 400, { start: true, end: false }],
    ])('shades the pinned edges that columns are scrolled under, %s', (_case, scrollLeft, expected) => {
        const { scrollWrapperTo, shadows } = render();

        scrollWrapperTo(scrollLeft);

        expect(shadows()).toEqual(expected);
    });

    it('puts the shadow edges on the last start-pinned and the first end-pinned cell of each row', () => {
        const { element } = render();

        const edgeLabels = (selector: string) =>
            [...element.querySelectorAll(`.table-header ${selector}`)].map((cell) => cell.textContent?.trim());
        expect(edgeLabels('.pinned-edge-start')).toEqual(['Name']);
        expect(edgeLabels('.pinned-edge-end')).toEqual(['Actions']);
        expect(element.querySelectorAll('.table-body .pinned-edge-start, .table-body .pinned-edge-end').length).toBe(2);
    });

    it('shows a scrollbar between the pinned columns whose thumb follows the wrapper scroll', () => {
        const { scrollWrapperTo, scrollbar } = render();
        scrollWrapperTo(0);

        const bar = scrollbar()!;
        // The checkbox and Name columns plus the left border; Actions plus the right border and vertical scrollbar (130 + 7).
        const calcTerms = (css: string) =>
            css
                .replace(/^calc\((.*)\)$/, '$1')
                .split(' + ')
                .sort();
        expect(calcTerms(bar.style.marginLeft)).toEqual(['1px', '200px', '2rem']);
        expect(calcTerms(bar.style.marginRight)).toEqual(['137px']);
        const thumb = bar.querySelector<HTMLElement>('.table-scrollbar__thumb')!;
        // 600px visible of 1000px.
        expect(thumb.style.width).toBe('60%');
        expect(thumb.style.left).toBe('0%');

        scrollWrapperTo(400);
        expect(thumb.style.left).toBe('40%');
    });

    it('scrolls the wrapper when the thumb is dragged or the track pressed', () => {
        const { wrapper, scrollWrapperTo, scrollbar, fixture } = render();
        scrollWrapperTo(0);
        const bar = scrollbar()!;
        const thumb = bar.querySelector<HTMLElement>('.table-scrollbar__thumb')!;
        bar.setPointerCapture = () => undefined;
        // A 500px track: a 300px thumb leaves 200px of travel for the 400px overflow, 2 scroll px per pointer px.
        bar.getBoundingClientRect = () => ({ left: 100, width: 500 }) as DOMRect;
        const pointer = (type: string, clientX: number, target: HTMLElement = bar) =>
            target.dispatchEvent(new PointerEvent(type, { clientX, button: 0, bubbles: true }));

        pointer('pointerdown', 150, thumb);
        pointer('pointermove', 200);
        expect(wrapper.scrollLeft).toBe(100);
        fixture.detectChanges();
        expect(bar.classList).toContain('table-scrollbar--dragging');
        pointer('pointerup', 200);
        pointer('pointermove', 300);
        expect(wrapper.scrollLeft).toBe(100);

        scrollWrapperTo(0);
        // Pressing the track at 300px centres the thumb there: its left edge 50px into the track, 100 scroll px.
        pointer('pointerdown', 300);
        expect(wrapper.scrollLeft).toBe(100);
    });

    it('shows no scrollbar while the columns fit', () => {
        const { wrapper, scrollWrapperTo, scrollbar } = render();
        Object.defineProperty(wrapper, 'scrollWidth', { value: 600, configurable: true });

        scrollWrapperTo(0);

        expect(scrollbar()).toBeNull();
    });

    it.each([
        ['a sideways swipe', { deltaX: 50 }, 50, true],
        ['shift + wheel', { deltaY: 50, shiftKey: true }, 50, true],
        ['a diagonal swipe, keeping its vertical part', { deltaX: 50, deltaY: 30 }, 50, false],
        ['a plain vertical wheel', { deltaY: 50 }, 0, false],
    ])('scrolls the wrapper sideways on %s', (_case, init, expectedScrollLeft, expectedPrevented) => {
        const { wrapper } = render();
        const wheel = new WheelEvent('wheel', { ...init, cancelable: true });

        wrapper.dispatchEvent(wheel);

        expect(wrapper.scrollLeft).toBe(expectedScrollLeft);
        expect(wheel.defaultPrevented).toBe(expectedPrevented);
    });

    it('keeps the native scrolling of a table without pinned columns', () => {
        const { wrapper, scrollWrapperTo, scrollbar } = render([
            { key: 'name', label: 'Name' },
            { key: 'owner', label: 'Owner' },
        ]);

        scrollWrapperTo(200);
        const wheel = new WheelEvent('wheel', { deltaX: 50, cancelable: true });
        wrapper.dispatchEvent(wheel);

        expect(wrapper.classList).not.toContain('table-wrapper--pinned');
        expect(scrollbar()).toBeNull();
        expect(wrapper.classList).not.toContain('table-wrapper--shadow-start');
        expect(wheel.defaultPrevented).toBe(false);
    });

    it('sizes a max-content end-pinned column to its widest cell and builds the offsets and scrollbar from it', () => {
        // A cell sized to `max-content` measures 10px per character of its text plus 24px of padding.
        vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
            const width = this.style.width === 'max-content' ? (this.textContent ?? '').trim().length * 10 + 24 : 0;
            return { width } as DOMRect;
        });
        const { element, scrollWrapperTo, scrollbar } = render([
            { key: 'name', label: 'Name', width: '200px', pinned: 'start' },
            { key: 'owner', label: 'Owner', width: '600px' },
            { key: 'status', label: 'Status', width: '100px', pinned: 'end' },
            { key: 'actions', label: 'Actions', width: 'max-content', pinned: 'end' },
        ]);

        TestBed.inject(ApplicationRef).tick();
        scrollWrapperTo(0);

        // "Actions" is the widest cell: 7 * 10 + 24.
        expect(element.querySelector<HTMLElement>('.table-header')!.style.gridTemplateColumns).toBe(
            '2rem 200px 600px 100px 94px'
        );
        const headerCell = (label: string) =>
            [...element.querySelectorAll<HTMLElement>('.table-header .table-cell')].find(
                (cell) => cell.textContent?.trim() === label
            )!;
        expect(headerCell('Actions').style.right).toBe('0px');
        expect(headerCell('Status').style.right).toBe('calc(94px)');
        // Actions, Status, and the right border plus vertical scrollbar (7).
        expect(scrollbar()!.style.marginRight).toBe('calc(201px)');
    });
});

@Component({
    imports: [AppTableComponent, AppTableCellDirective],
    template: `
        <app-table
            layoutKey="fit-spec-table"
            [columns]="columns"
            [data]="rows"
        >
            <ng-template
                appTableCell="name"
                let-row
            >
                <span class="cell-text">{{ row.name }}</span>
            </ng-template>
            <ng-template
                appTableCell="owner"
                let-row
            >
                <span class="cell-text">{{ row.owner }}</span>
            </ng-template>
        </app-table>
    `,
})
class FitColumnsHostComponent {
    readonly columns: AppTableColumnDef[] = [
        { key: 'name', label: 'Name', width: '200px', pinned: 'start' },
        { key: 'owner', label: 'Owner' },
        { key: 'sessions', label: 'Sessions' },
        { key: 'actions', label: 'Actions', width: '130px', pinned: 'end' },
    ];
    readonly rows: TableRow[] = [
        { id: 1, name: 'Alexandra Smith-Johnson', owner: 'Bo' },
        { id: 2, name: 'Al', owner: 'Ed' },
    ];
}

describe('AppTableComponent fit columns to the table', () => {
    afterEach(() => {
        localStorage.clear();
        vi.restoreAllMocks();
    });

    /**
     * jsdom does no layout. A cell sized to `max-content` measures 10px per character of its text plus 24px of
     * padding; any other cell (the end-pinned Actions one) measures 130px. The wrapper is 600px wide.
     */
    function render() {
        vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
            const width = this.style.width === 'max-content' ? (this.textContent ?? '').trim().length * 10 + 24 : 130;
            return { width } as DOMRect;
        });
        const fixture = TestBed.createComponent(FitColumnsHostComponent);
        fixture.detectChanges();
        const element = fixture.nativeElement as HTMLElement;
        Object.defineProperty(element.querySelector('.table-wrapper'), 'clientWidth', { value: 600 });
        const handle = (label: string) =>
            element.querySelector<HTMLElement>(`.resize-handle[aria-label="Resize ${label} column"]`)!;
        const gridTemplate = () => element.querySelector<HTMLElement>('.table-header')!.style.gridTemplateColumns;
        return { fixture, handle, gridTemplate };
    }

    it.each([
        [
            'double-clicking',
            (handle: HTMLElement) => handle.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })),
        ],
        [
            'pressing Enter on',
            (handle: HTMLElement) =>
                handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })),
        ],
    ])('%s any resize handle fits every resizable column into the table and stores the widths', (_case, trigger) => {
        const { fixture, handle, gridTemplate } = render();

        trigger(handle('Sessions'));
        fixture.detectChanges();

        // Content: Name 254 (its widest body cell), Owner 80 (minimum), Sessions 104 (its header), 438 in all.
        // 600 - 130 (Actions) = 470 leaves 32px, shared 11 + 11 + 10.
        expect(gridTemplate()).toBe('minmax(265px, 1fr) 91px 114px 130px');
        expect(handle('Owner').getAttribute('aria-valuenow')).toBe('91');
        expect(JSON.parse(localStorage.getItem('app-table-layout:fit-spec-table') ?? 'null')).toEqual({
            visibility: {},
            widths: { name: 265, owner: 91, sessions: 114 },
        });
    });

    it('leaves no cell sized to its content after measuring', () => {
        const { fixture, handle } = render();

        handle('Owner').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        fixture.detectChanges();

        expect(
            [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.table-cell')].filter(
                (cell) => cell.style.width
            )
        ).toEqual([]);
    });
});
